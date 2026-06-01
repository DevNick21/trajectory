from __future__ import annotations

import socket

import pytest

from askpicky.validators.url_safety import (
    UnsafeURL,
    assert_obviously_public_url,
    validate_public_fetch_url,
)


def test_obvious_guard_rejects_localhost():
    with pytest.raises(UnsafeURL):
        assert_obviously_public_url("http://localhost:8000/admin")


def test_obvious_guard_rejects_private_literal_ip():
    with pytest.raises(UnsafeURL):
        assert_obviously_public_url("https://10.0.0.5/job")


def test_obvious_guard_rejects_non_http_scheme():
    with pytest.raises(UnsafeURL):
        assert_obviously_public_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_validate_public_fetch_url_allows_public_dns(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):  # noqa: A002 - socket API name
        assert host == "example.com"
        assert port == 443
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert await validate_public_fetch_url("https://example.com/path") == "https://example.com/path"


@pytest.mark.asyncio
async def test_validate_public_fetch_url_rejects_private_dns(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):  # noqa: A002 - socket API name
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("192.168.1.10", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UnsafeURL):
        await validate_public_fetch_url("https://jobs.example.com")
