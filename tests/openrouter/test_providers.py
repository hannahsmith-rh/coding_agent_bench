import pytest

from coding_agent_bench.providers import (
    OPENROUTER_BASE_URL,
    is_openrouter,
    resolve_provider,
)


def test_is_openrouter_true():
    assert is_openrouter("openrouter") is True


def test_is_openrouter_false():
    assert is_openrouter("https://vllm.example.com") is False


def test_openrouter_base_url_excludes_v1():
    # Agents append /v1 as needed; claude-code uses the base without it.
    assert OPENROUTER_BASE_URL == "https://openrouter.ai/api"
    assert not OPENROUTER_BASE_URL.endswith("/v1")


def test_resolve_openrouter_returns_url_and_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    base_url, api_key = resolve_provider("openrouter")
    assert base_url == OPENROUTER_BASE_URL
    assert api_key == "sk-or-test"


def test_resolve_openrouter_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        resolve_provider("openrouter")


def test_resolve_non_openrouter_passthrough(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    base_url, api_key = resolve_provider("https://vllm.example.com")
    assert base_url == "https://vllm.example.com"
    assert api_key is None
