"""Validation helpers for intake requests and model server URLs."""

from collections.abc import Collection
import ipaddress
import os
import socket
from urllib.parse import urlparse

from coding_agent_bench.intake.config import ALLOWED_AGENTS, ALLOWED_DATASETS


def _configured_server_hosts(allowed_hosts: Collection[str] | None) -> set[str]:
    """Return normalized model-server hostnames from an argument or environment."""
    if allowed_hosts is None:
        raw_hosts = os.environ.get("ALLOWED_SERVER_HOSTS", "")
        allowed_hosts = raw_hosts.split(",")
    elif isinstance(allowed_hosts, str):
        allowed_hosts = allowed_hosts.split(",")
    return {host.strip().lower().rstrip(".") for host in allowed_hosts if host.strip()}


def _resolve_server_host(host: str, port: int | None) -> set[str]:
    """Resolve a hostname and return its addresses, raising on DNS failure."""
    try:
        results = socket.getaddrinfo(host, 443 if port is None else port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Server hostname '{host}' could not be resolved") from exc
    return {result[4][0] for result in results}


def _is_private_or_reserved(address: str) -> bool:
    """Return whether an address is unsafe for an externally hosted model server."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return any(
        (
            parsed.is_private,
            parsed.is_loopback,
            parsed.is_link_local,
            parsed.is_reserved,
            parsed.is_multicast,
            parsed.is_unspecified,
            not parsed.is_global,
        )
    )


def _is_ip_literal(host: str) -> bool:
    """Return whether a hostname string is an IPv4 or IPv6 literal."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def validate_server_url(
    server_url: str,
    allowed_hosts: Collection[str] | None = None,
) -> list[str]:
    """Validate an HTTPS model URL against the configured public-host allowlist.

    Hostnames are resolved during validation so private, loopback, link-local, and
    reserved addresses cannot be submitted as model endpoints. Cluster operators
    should also apply equivalent egress restrictions to worker pods because DNS can
    change after this check.
    """
    errors: list[str] = []
    parsed = urlparse(server_url)

    if parsed.scheme != "https":
        errors.append(f"Server URL must use https scheme, got '{parsed.scheme or 'none'}'")
        return errors
    if not parsed.netloc or parsed.hostname is None:
        errors.append("Server URL is not a valid URL")
        return errors
    if parsed.username or parsed.password:
        errors.append("Server URL must not contain username or password credentials")
        return errors

    try:
        port = parsed.port
    except ValueError:
        errors.append("Server URL contains an invalid port")
        return errors

    host = parsed.hostname.rstrip(".").lower()
    configured_hosts = _configured_server_hosts(allowed_hosts)
    if not configured_hosts:
        errors.append("Server hostname is not configured; set ALLOWED_SERVER_HOSTS")
        return errors
    if host not in configured_hosts:
        errors.append(f"Server hostname '{host}' is not in ALLOWED_SERVER_HOSTS")
        return errors

    try:
        addresses = {host} if _is_ip_literal(host) else _resolve_server_host(host, port)
    except ValueError as exc:
        errors.append(str(exc))
        return errors
    if not addresses:
        errors.append(f"Server hostname '{host}' did not resolve to an address")
        return errors

    blocked = sorted(address for address in addresses if _is_private_or_reserved(address))
    if blocked:
        errors.append(
            f"Server hostname '{host}' resolves to private or reserved address(es): "
            + ", ".join(blocked)
        )
    return errors


def validate_row(
    agent: str,
    dataset: str,
    server_url: str,
    allowed_hosts: Collection[str] | None = None,
) -> list[str]:
    """Return human-readable validation errors for one intake spreadsheet row."""
    errors: list[str] = []

    if agent not in ALLOWED_AGENTS:
        allowed = ", ".join(sorted(ALLOWED_AGENTS))
        errors.append(f"Unknown agent '{agent}'. Allowed: {allowed}")

    if dataset not in ALLOWED_DATASETS:
        allowed = ", ".join(sorted(ALLOWED_DATASETS))
        errors.append(f"Unknown dataset '{dataset}'. Allowed: {allowed}")

    if not server_url:
        errors.append("Server URL is empty")
    elif server_url.lower() != "openrouter":
        errors.extend(validate_server_url(server_url, allowed_hosts=allowed_hosts))

    return errors
