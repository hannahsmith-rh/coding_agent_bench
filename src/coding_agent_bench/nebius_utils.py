from abc import ABC
from pathlib import Path
import asyncio
import logging
import json
import shlex
import tempfile

from coding_agent_bench.models import get_model_config


logger = logging.getLogger(__name__)

class ResourceConfig(ABC):
    
    name: str
    platform: str
    preset: str
    additional_args: list[str] = []
    
class B200(ResourceConfig):
    
    name = "b200"
    platform = "gpu-b200-sxm"
    preset = "1gpu-20vcpu-224gb"
    additional_args = ["--preemptible-on-preemption", "stop", "--recovery-policy", "fail"]
    
class H200(ResourceConfig):

    name = "h200"
    platform = "gpu-h200-sxm"
    preset = "1gpu-16vcpu-200gb"

RESOURCE_CONFIGS: list[ResourceConfig] = [
    B200,
    H200,
]

RESOURCE_CONFIG_REGISTRY: dict[str, ResourceConfig] = {c.name: c for c in RESOURCE_CONFIGS}

class NebiusInstanceManager:
    """Manage Nebius compute instances via the nebius CLI."""

    def __init__(self, credentials_path: str | Path | None, user: str, ssh_public_key_path: str | Path, ssh_private_key_path: str | Path, parent_id: str, tenant_id: str, service_account_id: str, credentials: str | None = None):
        if credentials_path is None and credentials is None:
            raise ValueError("Either credentials_path or credentials must be provided")
        self._credentials_path = credentials_path
        self._credentials = credentials
        self._ssh_public_key_path = ssh_public_key_path
        self._ssh_private_key_path = ssh_private_key_path
        self._user = user
        self._parent_id = parent_id
        self._tenant_id = tenant_id
        self._service_account_id = service_account_id

        self._ssh_key = Path(self._ssh_public_key_path).expanduser().resolve().read_text()

    async def init(self):
        """Create the default CLI profile. Call once after construction."""
        if self._credentials_path:
            creds_path = Path(self._credentials_path).expanduser().resolve()
        else:
            f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            f.write(self._credentials)  # type: ignore[arg-type]  # validated non-None in __init__
            f.close()
            creds_path = Path(f.name)
        self.profile = await self.create_profile(
            "default-service-account",
            credentials_path=creds_path,
        )

    async def exec(self, args: list[str]) -> str:
        """Execute a nebius CLI command."""
        command = ["nebius"] + args
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        stdout = stdout_bytes.decode() if stdout_bytes else ""
        stderr = stderr_bytes.decode() if stderr_bytes else ""

        if process.returncode != 0:
            logger.info(f"Command failed: {command}\nstdout: {stdout}\nstderr: {stderr}")
            raise Exception(f"Failed to execute command: {command}\nstdout: {stdout}\nstderr: {stderr}")

        return stdout

    async def create_profile(self, name: str, credentials_path: Path):
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
            return await self.exec(args)
        except Exception as e:
            if "already exists" in str(e):
                logger.info("Profile already exists. Skipping creation.")
                return None
            else:
                raise e

    async def create_instance(self, instance_name: str, subnet_id: str, gpu_config: str = "h200"):
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

        # Get GPU config
        resource_config = RESOURCE_CONFIG_REGISTRY.get(gpu_config)
        if resource_config is None:
            raise ValueError(f"GPU config '{gpu_config}' is not recognized. Please choose from: {RESOURCE_CONFIG_REGISTRY.keys()}")

        # Build the create command
        args = [
            "compute", "v1", "instance", "create",
            "--parent-id", self._parent_id,
            "--name", instance_name,
            "--service-account-id", self._service_account_id,
            "--resources-platform", resource_config.platform,
            "--resources-preset", resource_config.preset,
            "--network-interfaces", json.dumps(network_interfaces),
            "--boot-disk-attach-mode", "read_write",
            "--boot-disk-managed-disk-name", f"{instance_name}-boot-disk",
            "--boot-disk-managed-disk-size-bytes", "1374389534720",
            "--boot-disk-managed-disk-block-size-bytes", "4096",
            "--boot-disk-managed-disk-type", "network_ssd",
            "--boot-disk-managed-disk-source-image-family-image-family", "ubuntu24.04-cuda13.0",
            "--boot-disk-device-id", "boot-disk",
            "--cloud-init-user-data", cloud_init_user_data,
            "--reservation-policy-policy", "forbid",
        ]
        args += resource_config.additional_args
        await self.exec(args)

    async def get_instance(self, instance_name: str):
        """Get details about a running instance."""
        args = [
            "compute", "instance", "get-by-name",
            "--name", instance_name,
            "--format", "json",
        ]
        stdout = await self.exec(args)
        return json.loads(stdout)

    async def get_instance_ip_address(self, instance_name: str):
        """Get the IP address of a running instance."""
        try:
            instance_details = await self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e

        return instance_details.get("status", {}).get("network_interfaces", [{}])[0].get("public_ip_address", {}).get("address")

    async def instance_exists(self, instance_name: str) -> bool:
        try:
            await self.get_instance(instance_name)
            return True
        except Exception as e:
            if "NotFound" in str(e):
                return False
            raise

    async def start_instance(self, instance_name: str):
        """Start a stopped instance."""
        try:
            instance_details = await self.get_instance(instance_name)
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
                await self.exec(args)
                logger.info(f"Instance {instance_name} ({instance_id}) started")
            except Exception as e:
                logger.error(f"Failed to start instance {instance_name}: {e}")
                raise e
            return

        else:
            logger.info(f"Instance {instance_name} ({instance_id}) is in an unknown state: {state}")

    async def stop_instance(self, instance_name: str):
        """Stop a running instance."""
        try:
            instance_details = await self.get_instance(instance_name)
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
            logger.info(f"Instance {instance_name} ({instance_id}) is already stopped")
            return

        if state == "RUNNING":
            try:
                logger.info(f"Stopping instance {instance_name} ({instance_id})")
                args = [
                    "compute", "instance", "stop",
                    "--id", instance_id,
                ]
                await self.exec(args)
                logger.info(f"Instance {instance_name} ({instance_id}) stopped")
            except Exception as e:
                logger.error(f"Failed to stop instance {instance_name}: {e}")
                raise e
            return

        else:
            logger.info(f"Instance {instance_name} ({instance_id}) is in an unknown state: {state}")

    async def delete_instance(self, instance_name: str):
        try:
            instance_details = await self.get_instance(instance_name)
        except Exception as e:
            if "NotFound" in str(e):
                raise ValueError("Instance not found")
            else:
                raise e

        state = instance_details.get("status", {}).get("state")
        instance_id = instance_details.get("metadata", {}).get("id")

        if state == "RUNNING":
            await self.stop_instance(instance_name)

        logger.info(f"Deleting instance {instance_name} ({instance_id})")
        args = [
            "compute", "instance", "delete",
            "--id", instance_id,
        ]
        await self.exec(args)

        logger.info(f"Deleted instance {instance_name} ({instance_id})")

    async def instance_exec(self, instance_name: str, command: list[str], exit_after: str | None = None, retries: int = 5, retry_delay: int = 10):
        """Connect to an instance over SSH and execute a command.

        Retries on SSH connection failures (e.g. VM just started and sshd
        isn't ready yet). CancelledError is always re-raised immediately
        so shutdown isn't blocked.
        """
        public_ip_address = await self.get_instance_ip_address(instance_name=instance_name)

        if public_ip_address is None:
            raise ValueError("Public IP address not found")

        if "/" in public_ip_address:
            public_ip_address = public_ip_address.split("/")[0]

        ssh_command = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-i", str(self._ssh_private_key_path),
            f"{self._user}@{public_ip_address}",
            shlex.join(command),
        ]

        logger.info(f"Executing command on {instance_name}: {command}")

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                if exit_after is None:
                    return await self._ssh_run(ssh_command)
                else:
                    return await self._ssh_stream(ssh_command, exit_after)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                if attempt < retries:
                    logger.warning(f"SSH attempt {attempt}/{retries} failed, retrying in {retry_delay}s: {e}")
                    await asyncio.sleep(retry_delay)

        raise last_error  # type: ignore[misc]

    async def _ssh_run(self, ssh_command: list[str]) -> str:
        """Run an SSH command and return stdout."""
        process = await asyncio.create_subprocess_exec(
            *ssh_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        stdout = stdout_bytes.decode() if stdout_bytes else ""
        stderr = stderr_bytes.decode() if stderr_bytes else ""
        if process.returncode != 0:
            raise Exception(f"SSH command failed:\nstdout: {stdout}\nstderr: {stderr}")
        return stdout

    async def _ssh_stream(self, ssh_command: list[str], exit_after: str) -> str:
        """Run an SSH command and stream stdout until exit_after marker is found."""
        logger.info(f"Following command until '{exit_after}' is found:")
        process = await asyncio.create_subprocess_exec(
            *ssh_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output_lines: list[str] = []
        try:
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode()
                output_lines.append(line)
                logger.info(line.rstrip())
                if exit_after in line:
                    process.terminate()
                    await process.wait()
                    return "".join(output_lines)
            await process.wait()
            if process.returncode != 0:
                assert process.stderr is not None
                stderr_bytes = await process.stderr.read()
                stderr = stderr_bytes.decode() if stderr_bytes else ""
                raise Exception(f"SSH command failed before '{exit_after}' was found:\nstdout: {''.join(output_lines)}\nstderr: {stderr}")
            raise Exception(f"Command finished without outputting '{exit_after}':\nstdout: {''.join(output_lines)}")
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except Exception:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

    async def start_model(self, instance_name: str, model_name: str):
        """Start a model on a Nebius instance."""
        # Fetch the model config
        model_config = get_model_config(model_name)

        # Get the instance
        try:
            instance_details = await self.get_instance(instance_name)
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
        command += ["--tensor-parallel-size", str(tensor_parallel_size)]

        # Execute the command on the instance
        # More retries than default — instance may have just booted and sshd isn't ready yet
        await self.instance_exec(instance_name=instance_name, command=command, exit_after="Available routes", retries=18, retry_delay=10)

    async def stop_model(self, instance_name: str):
        """Stop a running vLLM server on the given instance."""
        await self.instance_exec(instance_name, ["sudo", "docker", "stop", "vllm"])
        await self.instance_exec(instance_name, ["sudo", "docker", "rm", "vllm"])
