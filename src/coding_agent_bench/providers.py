import os

OPENROUTER_SENTINEL = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"

# Agents (SupportedAgent.value strings) that cannot use OpenRouter. This is
# only a fast, request-time 400 for create_job's lightweight openrouter
# validation branch; the authoritative guards live in each agent's own
# configure() (see OracleAgentConfig / ClaudeCodeAgentConfig), which still
# raise ValueError at build/run time regardless of this constant.
OPENROUTER_UNSUPPORTED_AGENTS = frozenset({"oracle", "claude-code"})


def is_openrouter(server_url: str) -> bool:
    """Return True if server_url is the OpenRouter sentinel."""
    return server_url == OPENROUTER_SENTINEL


def resolve_provider(server_url: str) -> tuple[str, str | None]:
    """Resolve server_url to (base_url, api_key).

    For the "openrouter" sentinel, return the OpenRouter base URL and the key
    from the OPENROUTER_API_KEY environment variable, raising ValueError if the
    key is not set. For any other server_url, return (server_url, None) so
    callers keep their existing no-auth behavior.
    """
    if is_openrouter(server_url):
        api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
        if not api_key:
            raise ValueError(
                f"server_url '{OPENROUTER_SENTINEL}' requires the "
                f"{OPENROUTER_API_KEY_ENV} environment variable to be set"
            )
        return OPENROUTER_BASE_URL, api_key
    return server_url, None
