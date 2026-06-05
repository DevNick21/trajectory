"""SSRF guard for every URL fetch path."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse, urlunparse


class UnsafeURL(ValueError):
    """Raised when a user-supplied URL is not safe to fetch server-side."""


_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}

_MAX_PORT = 65535


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _normalise_candidate(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL("Only http and https URLs are fetchable.")
    if not parsed.hostname:
        raise UnsafeURL("URL must include a hostname.")
    if parsed.username or parsed.password:
        raise UnsafeURL("Credential-bearing URLs are not fetchable.")
    host = parsed.hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        raise UnsafeURL("Local or metadata hostnames are not fetchable.")
    if parsed.port is not None and (parsed.port < 1 or parsed.port > _MAX_PORT):
        raise UnsafeURL("URL port is invalid.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(ip):
            raise UnsafeURL("Private, local, link-local, or reserved IPs are not fetchable.")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )


def _resolve_public(hostname: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL("URL hostname could not be resolved.") from exc
    if not infos:
        raise UnsafeURL("URL hostname could not be resolved.")
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeURL("URL resolved to an invalid address.") from exc
        if _is_blocked_ip(ip):
            raise UnsafeURL(
                "URL resolves to a private, local, link-local, or reserved address."
            )


async def validate_public_fetch_url(url: str) -> str:
    """Return a normalised URL after scheme, host, and DNS safety checks."""
    normalised = _normalise_candidate(url)
    parsed = urlparse(normalised)
    assert parsed.hostname is not None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    await asyncio.to_thread(_resolve_public, parsed.hostname, port)
    return normalised


def assert_obviously_public_url(url: str) -> str:
    """Cheap guard for browser subrequests where DNS per asset is too costly."""
    return _normalise_candidate(url)
