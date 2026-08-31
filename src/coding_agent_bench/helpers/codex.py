import json
from pathlib import Path

from coding_agent_bench.providers import OPENROUTER_API_KEY_ENV

TEMPLATE = """model = {model_name}
model_provider = "vllm"
web_search = "disabled"

[model_providers.vllm]
name = "vllm"
base_url = {base_url}
wire_api = {wire_api}
requires_openai_auth = {requires_openai_auth}
{env_key_line}[features]
js_repl = false
multi_agent = true
guardian_approval = true
prevent_idle_sleep = true
image_generation = false
"""


def _toml_string(value: str) -> str:
    return json.dumps(value)


def codex_create_toml(
    model_name: str, server_url: str, outpath: Path, openrouter: bool = False
):
    base_url = server_url.rstrip("/").removesuffix("/v1") + "/v1"
    if openrouter:
        # OpenRouter: chat-completions wire format with key auth. Codex reads the
        # key from the OPENROUTER_API_KEY env var (env_key), so the value itself
        # is never passed to or written by this function.
        wire_api = "chat"
        requires_openai_auth = "true"
        env_key_line = f"env_key = {_toml_string(OPENROUTER_API_KEY_ENV)}\n\n"
    else:
        # Default self-served vLLM: Responses API, no auth.
        wire_api = "responses"
        requires_openai_auth = "false"
        env_key_line = ""

    toml = TEMPLATE.format(
        model_name=_toml_string(model_name),
        base_url=_toml_string(base_url),
        wire_api=_toml_string(wire_api),
        requires_openai_auth=requires_openai_auth,
        env_key_line=env_key_line,
    )

    with open(outpath, "w") as f:
        f.write(toml)
