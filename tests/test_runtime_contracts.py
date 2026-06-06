from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from askpicky.llm_backends.openai_compat_backend import OpenAICompatBackend


class _DummyOutput(BaseModel):
    ok: bool


class _FakeResponse:
    status_code = 200
    text = '{"ok": true}'

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"ok": True})},
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        }


class _FakeClient:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    async def post(self, path: str, *, json: dict) -> _FakeResponse:
        assert path == "/chat/completions"
        self.bodies.append(json)
        return _FakeResponse()


@pytest.mark.asyncio
async def test_openai_compat_backend_uses_provider_specific_token_parameter():
    fake_client = _FakeClient()
    backend = OpenAICompatBackend(api_key="test", supports_json_schema=True)
    backend._client = fake_client

    await backend.call(
        system_prompt="Return JSON.",
        messages=[{"role": "user", "content": "ok"}],
        output_schema=_DummyOutput,
        model="gpt-test",
        provider="openai",
        max_tokens=123,
    )
    await backend.call(
        system_prompt="Return JSON.",
        messages=[{"role": "user", "content": "ok"}],
        output_schema=_DummyOutput,
        model="deepseek-test",
        provider="deepseek",
        max_tokens=456,
    )

    openai_body, deepseek_body = fake_client.bodies
    assert openai_body["max_completion_tokens"] == 123
    assert "max_tokens" not in openai_body
    assert deepseek_body["max_tokens"] == 456
    assert "max_completion_tokens" not in deepseek_body


def test_definite_pass_headline_handles_short_jd_reason():
    from askpicky.orchestrator import _triage_pass_headline

    headline = _triage_pass_headline(
        "JD is too short to evaluate (under 60 characters)."
    )

    assert headline == "Skip - JD is too short to evaluate."
    assert len(headline.split()) <= 12


def test_candidate_urls_are_bounded_and_include_high_signal_pages():
    from askpicky.sub_agents import company_scraper

    urls = company_scraper._candidate_urls("deel.com")

    assert len(urls) == len(company_scraper._CANDIDATE_FETCH_PATHS)
    assert len(urls) < len(company_scraper._CANDIDATE_PATHS)
    assert "https://deel.com/careers" in urls
    assert "https://deel.com/about" in urls
    assert "https://deel.com/legal" in urls


@pytest.mark.asyncio
async def test_candidate_fetch_limits_firecrawl_fallbacks(monkeypatch):
    from askpicky import firecrawl
    from askpicky.sub_agents import company_scraper

    firecrawl_calls: list[str] = []

    async def fake_fetch_html(url: str, **_kwargs):
        return None

    async def fake_firecrawl_scrape(url: str, **_kwargs):
        firecrawl_calls.append(url)
        return "rescued candidate page " + ("x" * 250)

    monkeypatch.setattr(company_scraper, "_fetch_html", fake_fetch_html)
    monkeypatch.setattr(firecrawl, "firecrawl_scrape", fake_firecrawl_scrape)

    urls = [f"https://example.com/page-{idx}" for idx in range(5)]

    results = await company_scraper._fetch_candidates(urls)

    assert len(firecrawl_calls) == company_scraper._MAX_CANDIDATE_FIRECRAWL_FALLBACKS
    assert len(results) == company_scraper._MAX_CANDIDATE_FIRECRAWL_FALLBACKS
