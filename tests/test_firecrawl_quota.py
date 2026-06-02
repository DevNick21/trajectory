from __future__ import annotations

import pytest

from askpicky.firecrawl import firecrawl_scrape


class _DenyingStorage:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_quota_usage(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "allowed": False,
            "category": kwargs["category"],
            "period": "2026-06",
            "limit": 0,
            "used": 0,
        }


@pytest.mark.asyncio
async def test_firecrawl_quota_denial_skips_external_call(monkeypatch):
    from askpicky.config import settings

    storage = _DenyingStorage()
    monkeypatch.setattr(settings, "firecrawl_api_key", "test-key")
    monkeypatch.setattr(settings, "enforce_hosted_quotas", True)

    async def _safe(url: str) -> str:
        return url

    monkeypatch.setattr("askpicky.firecrawl.validate_public_fetch_url", _safe)

    result = await firecrawl_scrape(
        "https://example.com/jobs/1",
        user_id="user-123",
        storage=storage,
        metadata={"caller": "test"},
    )

    assert result is None
    assert storage.calls == [{
        "user_id": "user-123",
        "category": "firecrawl",
        "units": 1,
        "metadata": {
            "url": "https://example.com/jobs/1",
            "caller": "test",
        },
    }]
