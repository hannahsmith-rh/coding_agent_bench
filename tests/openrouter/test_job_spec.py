from coding_agent_bench.job import OpenshiftJob


def _env_by_name(spec):
    container = spec["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e for e in container["env"]}


def test_job_spec_includes_optional_openrouter_secret():
    job = OpenshiftJob(job_name="test")
    env = _env_by_name(job._job_spec(["echo", "hi"]))
    assert "OPENROUTER_API_KEY" in env
    ref = env["OPENROUTER_API_KEY"]["valueFrom"]["secretKeyRef"]
    assert ref["name"] == "openrouter"
    assert ref["key"] == "OPENROUTER_API_KEY"
    assert ref["optional"] is True


def test_resume_job_spec_includes_optional_openrouter_secret():
    job = OpenshiftJob(job_name="test")
    env = _env_by_name(job._resume_job_spec("echo hi"))
    assert "OPENROUTER_API_KEY" in env
    ref = env["OPENROUTER_API_KEY"]["valueFrom"]["secretKeyRef"]
    assert ref["optional"] is True
