import socket

from coding_agent_bench.intake.validation import validate_row, validate_server_url


def test_valid_row_returns_no_errors():
    """Accept a configured public HTTPS model endpoint."""
    errors = validate_row(
        agent="codex",
        dataset="swe-bench/swe-bench-verified",
        server_url="https://vllm.example.com",
    )
    assert errors == []


def test_unknown_agent():
    """Reject an agent outside the supported intake set."""
    errors = validate_row(
        agent="not-a-real-agent",
        dataset="swe-bench/swe-bench-verified",
        server_url="https://vllm.example.com",
    )
    assert len(errors) == 1
    assert "agent" in errors[0].lower()


def test_unknown_dataset():
    """Reject a dataset outside the supported intake set."""
    errors = validate_row(
        agent="codex",
        dataset="fake-dataset-999",
        server_url="https://vllm.example.com",
    )
    assert len(errors) == 1
    assert "dataset" in errors[0].lower()


def test_invalid_url_no_scheme():
    """Reject a model endpoint without an HTTPS scheme."""
    errors = validate_row(
        agent="codex",
        dataset="swe-bench/swe-bench-verified",
        server_url="vllm.example.com",
    )
    assert len(errors) == 1
    assert "url" in errors[0].lower()


def test_invalid_url_http_not_https():
    """Reject plaintext model endpoints."""
    errors = validate_row(
        agent="codex",
        dataset="swe-bench/swe-bench-verified",
        server_url="http://vllm.example.com",
    )
    assert len(errors) == 1
    assert "https" in errors[0].lower()


def test_empty_url():
    """Reject an empty model endpoint."""
    errors = validate_row(
        agent="codex",
        dataset="swe-bench/swe-bench-verified",
        server_url="",
    )
    assert len(errors) >= 1


def test_openrouter_url_accepted():
    """Allow the OpenRouter sentinel without URL parsing."""
    errors = validate_row(
        agent="codex",
        dataset="swe-bench/swe-bench-verified",
        server_url="openrouter",
    )
    assert errors == []


def test_multiple_errors():
    """Report independent agent, dataset, and URL validation errors."""
    errors = validate_row(
        agent="bad-agent",
        dataset="bad-dataset",
        server_url="not-a-url",
    )
    assert len(errors) == 3


def test_server_host_must_be_allowlisted():
    """Reject a public-looking hostname that is not explicitly configured."""
    errors = validate_server_url(
        "https://other.example.com",
        allowed_hosts={"vllm.example.com"},
    )
    assert any("allow" in error.lower() for error in errors)


def test_literal_private_address_is_rejected():
    """Reject loopback addresses even when someone adds them to the allowlist."""
    errors = validate_server_url(
        "https://127.0.0.1:8443",
        allowed_hosts={"127.0.0.1"},
    )
    assert any("private" in error.lower() or "reserved" in error.lower() for error in errors)


def test_dns_private_address_is_rejected(monkeypatch):
    """Reject an allowlisted hostname that resolves to a private address."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))
        ],
    )
    errors = validate_server_url(
        "https://vllm.example.com",
        allowed_hosts={"vllm.example.com"},
    )
    assert any("private" in error.lower() for error in errors)
