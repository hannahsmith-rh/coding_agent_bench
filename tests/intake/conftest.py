import socket

import pytest


@pytest.fixture(autouse=True)
def configure_server_url_validation(monkeypatch: pytest.MonkeyPatch):
    """Configure a public test hostname without making network DNS calls."""
    monkeypatch.setenv("ALLOWED_SERVER_HOSTS", "vllm.example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
