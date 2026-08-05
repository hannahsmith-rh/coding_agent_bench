from abc import ABC
from os import PathLike
from pathlib import Path
import logging
import shlex
import subprocess
import json

from coding_agent_bench.models import get_model_config


logger = logging.getLogger(__name__)


class NebiusInstanceManager:
    """Manage Nebius compute instances."""
    
    def __init__(self, credentials_path: str | Path, user: str, ssh_public_key_path: str | Path, ssh_private_key_path: str | Path, parent_id: str, tenant_id: str, service_account_id: str):
        self._credentials_path = credentials_path
        self._ssh_public_key_path = ssh_public_key_path
        self._ssh_private_key_path = ssh_private_key_path
        self._user = user
        self._parent_id = parent_id
        self._tenant_id = tenant_id
        self._service_account_id = service_account_id
        
        self._ssh_key = Path(self._ssh_public_key_path).expanduser().resolve().read_text()

        self.profile = self.create_profile("default-service-account", credentials_path=Path(credentials_path).expanduser().resolve())
        self.instances: dict[str, dict] = {}
        
    def exec(self, args: list[str]):
        """Execute a nebius CLI command."""
        command = ["nebius"] + args
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if process.returncode != 0:
            logger.info(f"Command failed: {command}\nstdout: {process.stdout}\nstderr: {process.stderr}")
            raise Exception(f"Failed to execute command: {command}\nstdout: {process.stdout}\nstderr: {process.stderr}")

        return process.stdout
            
    def get_instances(self):
        """Get a list of all compute instances managed by this object."""
        return self.instances
    
    def create_profile(self, name: str, credentials_path: Path):
        """Create a new service account profile."""
        try:        
            args = [
                "profile", "create",
                "--endpoint", "api.nebius.cloud",
                "--parent-id", self._parent_id,
                "--tenant-id", self._tenant_id,
                "--service-account-file", str(credentials_path),
                "--profile", name,
            ]
            return self.exec(args)
        except Exception as e:
            if "already exists" in str(e):
                logger.info("Profile already exists. Skipping creation.")
                return None
            else:
                raise e
    
    def create_instance(self, instance_name: str, subnet_id: str, gpu_config: str = "h200"):
        """Create a new compute instance."""
        cloud_init_user_data = (
            "users:\n"
            f"  - name: {self._user}\n"
            "    sudo: ALL=(ALL) NOPASSWD:ALL\n"
            "    shell: /bin/bash\n"
            "    ssh_authorized_keys:\n"
            f"      - {self._ssh_key}\n"
        )
        network_interfaces = [{"subnetId": subnet_id, "name": "eth0", "ipAddress": {}, "publicIpAddress": {}}]
        
        if gpu_config == "b200":
            platform = "gpu-b200-sxm"
            preset = "1gpu-20vcpu-224gb"
        elif gpu_config == "h200":
            platform = "gpu-h200-sxm"
            preset = "1gpu-16vcpu-200gb"
            
        args = [
            "compute", "v1", "instance", "create",
            "--parent-id", self._parent_id,
            "--name", instance_name,
            "--service-account-id", self._service_account_id,
            "--resources-platform", platform,
            "--resources-preset", preset,
            "--network-interfaces", json.dumps(network_interfaces),
            "--boot-disk-attach-mode", "read_write",
            "--boot-disk-managed-disk-name", f"{instance_name}-boot-disk",
            "--boot-disk-managed-disk-size-bytes", "1374389534720",
            "--boot-disk-managed-disk-block-size-bytes", "4096",
            "--boot-disk-managed-disk-type", "network_ssd",
            "--boot-disk-managed-disk-source-image-family-image-family", "ubuntu24.04-cuda13.0",
            "--boot-disk-device-id", "boot-disk",
            "--cloud-init-user-data", cloud_init_user_data,
            "--reservation-policy-policy", "forbid"
        ]
        self.exec(args)
        
        instance_details = self.get_instance(instance_name)
        self.instances["instance_name"] = instance_details["metadata"]

    def get_instance(self, instance_name: str):
        """Get details about a running instance."""
        args = [
            "compute", "instance", "get-by-name",
            "--name", instance_name,
            "--format", "json",
        ]
        stdout = self.exec(args)
        return json.loads(stdout)
    
    def get_instance_ip_address(self, instance_name: str):
        """Get the IP address of a running instance."""
        try:
            instance_details = self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e
        
        return instance_details.get("status", {}).get("network_interfaces", [{}])[0].get("public_ip_address", {}).get("address")

    def start_instance(self, instance_name: str):
        """Start a stopped instance."""
        try:
            instance_details = self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e
        
        state = instance_details.get("status", {}).get("state")
        instance_id = instance_details.get("metadata", {}).get("id")
        
        if state is None:
            raise ValueError("Instance state is not available")
        
        if state == "RUNNING":
            logger.info(f"Instance {instance_name} ({instance_id}) is already running")
            return
        
        if state in ["STOPPED", "STOPPING"]:
            try:
                logger.info(f"Starting instance {instance_name} ({instance_id})")
                args = [
                    "compute", "instance", "start",
                    "--id", instance_id,
                ]
                self.exec(args)
                logger.info(f"Instance {instance_name} ({instance_id}) started")
            except Exception as e:
                logger.error(f"Failed to start instance {instance_name}: {e}")
                raise e
            return
        
        else:
            logger.info(f"Instance {instance_name} ({instance_id}) is in an unknown state: {state}")
    
    def stop_instance(self, instance_name: str):
        """Stop a running instance."""
        try:
            instance_details = self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e
        
        state = instance_details.get("status", {}).get("state")
        instance_id = instance_details.get("metadata", {}).get("id")
            
        if state is None:
            raise ValueError("Instance state is not available")
        
        if state in ["STOPPED", "STOPPING"]:
            logger.info(f"Instance {instance_name} ({instance_id}) is already running")
            return
        
        if state == "RUNNING":
            try:
                logger.info(f"Stopping instance {instance_name} ({instance_id})")
                args = [
                    "compute", "instance", "stop",
                    "--id", instance_id,
                ]
                self.exec(args)
                logger.info(f"Instance {instance_name} ({instance_id}) stopped")
            except Exception as e:
                logger.error(f"Failed to stop instance {instance_name}: {e}")
                raise e
            return
        
        else:
            logger.info(f"Instance {instance_name} ({instance_id}) is in an unknown state: {state}")
            
    def delete_instance(self, instance_name: str):
        try:
            instance_details = self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e
            
        state = instance_details.get("status", {}).get("state")
        instance_id = instance_details.get("metadata", {}).get("id")
        
        if state == "RUNNING":
            self.stop_instance(instance_name)

        logger.info(f"Deleting instance {instance_name} ({instance_id})")
        args = [
            "compute", "instance", "delete",
            "--id", instance_id,
        ]
        self.exec(args)
        
        self.instances.pop(instance_name, None)
        logger.info(f"Deleted instance {instance_name} ({instance_id})")
        
    def instance_exec(self, instance_name: str, command: list[str], exit_after: str = None):
        """Connect to an instance over SSH and execute a command."""
        public_ip_address = self.get_instance_ip_address(instance_name=instance_name)

        if public_ip_address is None:
            raise ValueError("Public IP address not found")
        
        if "/" in public_ip_address:
            public_ip_address = public_ip_address.split("/")[0]

        ssh_command = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-i", str(self._ssh_private_key_path),
            f"{self._user}@{public_ip_address}",
            shlex.join(command),
        ]

        logger.info(f"Executing command  on {instance_name}: {command}")
        logger.info(f"SSH command: {ssh_command}")
        if exit_after is None:
            process = subprocess.run(ssh_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if process.returncode != 0:
                raise Exception(f"SSH command failed:\nstdout: {process.stdout}\nstderr: {process.stderr}")
            return process.stdout

        logger.info(f"Following command until '{exit_after}' is found:")
        process = subprocess.Popen(ssh_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output_lines = []
        try:
            for line in process.stdout:
                output_lines.append(line)
                logger.info(line.rstrip())
                if exit_after in line:
                    process.terminate()
                    return "".join(output_lines)
            process.wait()
            if process.returncode != 0:
                stderr = process.stderr.read()
                raise Exception(f"SSH command failed before '{exit_after}' was found:\nstdout: {''.join(output_lines)}\nstderr: {stderr}")
            raise Exception(f"Command finished without outputting '{exit_after}':\nstdout: {''.join(output_lines)}")
        except Exception:
            process.kill()
            raise

    def start_model(self, instance_name: str, model_name: str):
        """Start a model on a Nebius instance."""
        # Fetch the model config
        model_config = get_model_config(model_name)
        
        # Get the instance
        try:
            instance_details = self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e
        
        # Get the number of gpus from resources (e.g. 1gpu-16vcpu-200gb)
        resources = instance_details.get("spec", {}).get("resources", {}).get("preset")
        if resources is None:
            raise ValueError("Unable to get resources from instance details")
        tensor_parallel_size = int(resources.split("-")[0].replace("gpu", ""))
        
        # Build the vLLM command
        command = [
            "sudo", "docker", "run",
            "--name", "vllm",
            "--runtime", "nvidia",
            "--gpus", "all",
            "-v", "/home/.cache/huggingface:/root/.cache/huggingface",
            "--env", "HF_TOKEN=$HF_TOKEN",
            "-p", "8000:8000",
            "--ipc=host",
        ]
        command += [model_config.image]
        command += model_config.args + model_config.default_args
        command += ["--tensor_parallel_size", str(tensor_parallel_size)]
        
        # Execute the command on the instance
        self.instance_exec(instance_name=instance_name, command=command, exit_after="Application ready")

    def stop_model(self, instance_name: str):
        """Stop a running vLLM server on the given instance."""
        self.instance_exec(instance_name, ["sudo", "docker", "stop", "vllm"])
        self.instance_exec(instance_name, ["sudo", "docker", "rm", "vllm"])    
