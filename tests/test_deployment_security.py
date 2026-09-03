"""Deployment and worker-network security regression tests."""

from pathlib import Path

import yaml

from coding_agent_bench import api
from coding_agent_bench.job import OpenshiftJob


DEPLOYMENT_PATH = Path(__file__).parents[1] / "deploy" / "job-queue-service.yml"


def _deployment_objects() -> dict[str, dict]:
    """Return queue manifest objects indexed by Kubernetes kind."""
    with DEPLOYMENT_PATH.open() as manifest:
        objects = list(yaml.safe_load_all(manifest))
    return {obj["kind"]: obj for obj in objects}


def test_queue_manifest_encrypts_service_and_route():
    """Serve queue traffic with application TLS and an OpenShift reencrypt Route."""
    objects = _deployment_objects()
    deployment = objects["Deployment"]
    service = objects["Service"]
    route = objects["Route"]

    container = deployment["spec"]["template"]["spec"]["containers"][0]
    command = container["args"][0]
    assert "--port 8443" in command
    assert "--ssl-certfile /etc/job-queue/tls/tls.crt" in command
    assert "--ssl-keyfile /etc/job-queue/tls/tls.key" in command
    assert service["metadata"]["annotations"][
        "service.beta.openshift.io/serving-cert-secret-name"
    ] == "job-queue-tls"
    assert service["spec"]["ports"][0]["port"] == 443
    assert service["spec"]["ports"][0]["targetPort"] == 8443
    assert route["spec"]["tls"]["termination"] == "reencrypt"


def test_task_egress_policy_does_not_select_orchestrator_pods():
    """Keep OpenShift API access on the queue's orchestrator pod."""
    objects = _deployment_objects()
    policy_selector = objects["NetworkPolicy"]["spec"]["podSelector"]["matchLabels"]
    orchestrator_labels = OpenshiftJob("security-test")._job_spec(["echo", "ok"])[
        "spec"
    ]["template"]["metadata"]["labels"]

    assert policy_selector == {"app": "harbor", "component": "task"}
    assert orchestrator_labels == {"app": "harbor", "component": "orchestrator"}


def test_managed_worker_endpoint_must_be_public():
    """Revalidate provider-generated endpoints before launching a worker pod."""
    assert api._worker_server_url_errors(
        "http://93.184.216.34:8000", managed_endpoint=True
    ) == []
    errors = api._worker_server_url_errors(
        "http://169.254.169.254:8000", managed_endpoint=True
    )
    assert errors
    assert "private" in errors[0] or "reserved" in errors[0]
