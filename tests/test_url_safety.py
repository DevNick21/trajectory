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


@pytest.mark.asyncio
async def test_httpx_fetch_revalidates_redirect_target(monkeypatch):
    from askpicky.sub_agents import company_scraper

    def fake_getaddrinfo(host, port, type=0):  # noqa: A002 - socket API name
        assert host == "safe.example"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port),
            )
        ]

    calls: list[str] = []

    class _RedirectResponse:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data"}
        text = ""
        url = "https://safe.example/start"

        @property
        def is_redirect(self) -> bool:
            return True

    class _Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str):
            calls.append(url)
            return _RedirectResponse()

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(company_scraper.httpx, "AsyncClient", _Client)

    with pytest.raises(UnsafeURL):
        await company_scraper._fetch_with_httpx("https://safe.example/start")

    assert calls == ["https://safe.example/start"]
