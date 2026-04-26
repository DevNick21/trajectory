"""Tests for src/trajectory/managed/company_investigator.py.

Fully mocked — no Anthropic SDK calls, no network, no file system
(cache redirected to a tempdir). Exercises the integration by scripting
an event stream through `_events.consume_stream` and asserting the
end-to-end conversion, citation validation, archive/delete lifecycle,
and Content Shield invocation.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from trajectory.managed import _resources
from trajectory.managed.company_investigator import (
    ManagedInvestigatorFailed,
    investigate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_JOB_URL = "https://example.com/jobs/senior-engineer"
_CAREERS_URL = "https://example.com/careers"
_ABOUT_URL = "https://example.com/about"


def _extracted_jd_dict() -> dict:
    return {
        "role_title": "Senior Backend Engineer",
        "seniority_signal": "senior",
        "soc_code_guess": "2136",
        "soc_code_reasoning": "Software development role (SOC 2020 2136).",
        "salary_band": None,
        "location": "London",
        "remote_policy": "hybrid",
        "required_years_experience": 5,
        "required_years_experience_range": None,
        "required_skills": ["Python", "AWS"],
        "posted_date": "2026-04-15",
        "posting_platform": "company_site",
        "hiring_manager_named": True,
        "hiring_manager_name": "Alex Fernandez",
        "jd_text_full": "Senior Backend role. Python. AWS. 5+ years.",
        "specificity_signals": ["named hiring manager"],
        "vagueness_signals": [],
    }


def _investigator_output_json(culture_snippet: str) -> str:
    payload = {
        "company_name": "Example Ltd",
        "company_domain": "example.com",
        "culture_claims": [
            {
                "claim": "Culture values deep focus.",
                "source_url": _ABOUT_URL,
                "verbatim_snippet": culture_snippet,
            }
        ],
        "tech_stack_signals": [],
        "team_size_signals": [],
        "recent_activity_signals": [],
        "posted_salary_bands": [],
        "careers_page_url": _CAREERS_URL,
        "not_on_careers_page": False,
        "extracted_jd": _extracted_jd_dict(),
        "investigation_notes": "Fetched JD, careers, and about page.",
    }
    return json.dumps(payload)


class _FakeEvent:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)


class _FakeStream:
    """Async context manager yielding a scripted sequence of events."""

    def __init__(self, events: list[_FakeEvent]):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _build_mock_client(
    events: list[_FakeEvent],
    *,
    session_usage_input: int = 1200,
    session_usage_output: int = 800,
) -> MagicMock:
    """Construct a mock AsyncAnthropic client with the beta namespace."""
    client = MagicMock()

    # Agent + environment
    client.beta.agents.create = AsyncMock(
        return_value=MagicMock(id="agt_fake", version=1)
    )
    client.beta.environments.create = AsyncMock(
        return_value=MagicMock(id="env_fake")
    )

    # Session lifecycle
    client.beta.sessions.create = AsyncMock(return_value=MagicMock(id="sesn_fake"))
    client.beta.sessions.archive = AsyncMock(return_value=None)
    client.beta.sessions.delete = AsyncMock(return_value=None)

    # Usage retrieval
    retrieved = MagicMock()
    retrieved.usage = MagicMock(
        input_tokens=session_usage_input,
        output_tokens=session_usage_output,
    )
    client.beta.sessions.retrieve = AsyncMock(return_value=retrieved)

    # Events. AsyncAnthropic's events.stream(...) is an async def that
    # resolves to the async context manager — match that shape with
    # AsyncMock so the production `async with await ...` pattern works.
    client.beta.sessions.events.send = AsyncMock(return_value=None)

    stream = _FakeStream(events)
    client.beta.sessions.events.stream = AsyncMock(return_value=stream)

    return client


@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path: Path, monkeypatch):
    """Every test gets a fresh empty cache in tmp_path."""
    monkeypatch.setattr(_resources, "_CACHE_PATH", tmp_path / "managed_agents.json")
    yield


@pytest.fixture
def mock_anthropic(monkeypatch):
    """Monkeypatch `AsyncAnthropic` inside company_investigator so
    `from anthropic import AsyncAnthropic` returns our mock."""
    import anthropic

    def _inject(client_instance):
        class _FakeAsyncAnthropic:
            def __init__(self, *args, **kwargs):
                # Return our pre-configured client by making this a
                # singleton-style factory.
                pass

            def __new__(cls, *args, **kwargs):
                return client_instance

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)

    return _inject


@pytest.fixture(autouse=True)
def _no_shield_tier2(monkeypatch):
    """Bypass Tier 2 Sonnet calls — smoke-test-shaped tier1 only."""
    from trajectory.validators import content_shield

    async def _fake_shield(*, content, source_type, downstream_agent):
        # Return cleaned text as-is (tier1 passthrough), no verdict.
        return content, None

    monkeypatch.setattr(content_shield, "shield", _fake_shield)


@pytest.fixture(autouse=True)
def _no_cost_log(monkeypatch):
    """Sidestep the SQLite cost log — tests run with no DB."""
    from trajectory.managed import company_investigator

    logged = []

    async def _fake_log(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(company_investigator, "log_llm_cost", _fake_log)
    return logged


# ---------------------------------------------------------------------------
# Scenario: successful investigation
# ---------------------------------------------------------------------------


def _happy_path_events() -> list[_FakeEvent]:
    """Scripted sequence: 2 web_fetch calls then final JSON then idle."""
    culture_snippet = "We hire for deep focus and long attention spans."
    final_msg = _investigator_output_json(culture_snippet)

    return [
        # First web_fetch: the JD page
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_1",
            input={"url": _JOB_URL},
        ),
        _FakeEvent(
            type="agent.tool_result",
            tool_use_id="tu_1",
            content=[
                {"type": "text", "text": f"Job description body text for {_JOB_URL}."}
            ],
        ),
        # Second web_fetch: the about page
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_2",
            input={"url": _ABOUT_URL},
        ),
        _FakeEvent(
            type="agent.tool_result",
            tool_use_id="tu_2",
            content=[
                {
                    "type": "text",
                    "text": (
                        f"About Example Ltd. {culture_snippet} "
                        "Founded 2019."
                    ),
                }
            ],
        ),
        # Span usage event
        _FakeEvent(
            type="span.model_request_end",
            model_usage=MagicMock(input_tokens=500, output_tokens=300),
        ),
        # Final agent.message with the JSON
        _FakeEvent(
            type="agent.message",
            content=[{"type": "text", "text": final_msg}],
        ),
        # Terminate
        _FakeEvent(type="session.status_idle"),
    ]


@pytest.mark.asyncio
async def test_happy_path_returns_company_research(mock_anthropic, _no_cost_log):
    client = _build_mock_client(_happy_path_events())
    mock_anthropic(client)

    research, extracted_jd = await investigate(
        job_url=_JOB_URL, session_id="traj-session-xyz"
    )

    assert research.company_name == "Example Ltd"
    assert research.company_domain == "example.com"
    assert len(research.culture_claims) == 1
    assert research.culture_claims[0].url == _ABOUT_URL
    assert extracted_jd.role_title == "Senior Backend Engineer"
    assert extracted_jd.posted_date == date(2026, 4, 15)

    # Session archived (happy path) and retrieve called for usage.
    client.beta.sessions.archive.assert_called_once_with("sesn_fake")
    client.beta.sessions.delete.assert_not_called()
    client.beta.sessions.retrieve.assert_called_once_with("sesn_fake")

    # Cost log fired once with authoritative session totals.
    assert len(_no_cost_log) == 1
    logged = _no_cost_log[0]
    assert logged["agent_name"] == "managed_company_investigator"
    assert logged["input_tokens"] == 1200
    assert logged["output_tokens"] == 800


# ---------------------------------------------------------------------------
# Scenario: verbatim snippet not present in any fetched page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paraphrased_snippet_raises_and_deletes(mock_anthropic):
    """Citation not found in any fetched page → ManagedInvestigatorFailed
    and session.delete called (not archive)."""
    # Snippet the agent claims was in the page, but isn't.
    events = _happy_path_events()
    # Replace the final JSON with one whose snippet doesn't appear in
    # the about-page text.
    events[-2] = _FakeEvent(
        type="agent.message",
        content=[{
            "type": "text",
            "text": _investigator_output_json(
                "Invented paraphrase that doesn't appear anywhere.",
            ),
        }],
    )
    client = _build_mock_client(events)
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "verbatim_snippet not found" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")
    client.beta.sessions.archive.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: session terminates early
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_early_termination_raises_and_deletes(mock_anthropic):
    events = [
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_1",
            input={"url": _JOB_URL},
        ),
        _FakeEvent(
            type="session.status_terminated",
            error=MagicMock(message="sandbox crashed"),
        ),
    ]
    client = _build_mock_client(events)
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "terminated early" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")
    client.beta.sessions.archive.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: no final JSON emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_final_json_raises(mock_anthropic):
    events = [
        _FakeEvent(
            type="agent.tool_use",
            name="web_fetch",
            id="tu_1",
            input={"url": _JOB_URL},
        ),
        _FakeEvent(
            type="agent.tool_result",
            tool_use_id="tu_1",
            content=[{"type": "text", "text": "JD body."}],
        ),
        _FakeEvent(type="session.status_idle"),
    ]
    client = _build_mock_client(events)
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "parseable JSON" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")


# ---------------------------------------------------------------------------
# Scenario: Content Shield rejects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shield_reject_raises_and_deletes(mock_anthropic, monkeypatch):
    """REJECT verdict on a scraped page → investigator raises + deletes."""
    from trajectory.managed import company_investigator
    from trajectory.schemas import ContentShieldVerdict

    reject_verdict = ContentShieldVerdict(
        classification="MALICIOUS",
        reasoning="prompt injection detected",
        residual_patterns_detected=["role_switch"],
        recommended_action="REJECT",
    )

    async def _reject_shield(*, content, source_type, downstream_agent):
        return content, reject_verdict

    monkeypatch.setattr(company_investigator, "shield_content", _reject_shield)

    client = _build_mock_client(_happy_path_events())
    mock_anthropic(client)

    with pytest.raises(ManagedInvestigatorFailed) as exc_info:
        await investigate(job_url=_JOB_URL)
    assert "content shield rejected" in str(exc_info.value)

    client.beta.sessions.delete.assert_called_once_with("sesn_fake")
    client.beta.sessions.archive.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: resource caching — second call does not recreate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_reuse_across_invocations(mock_anthropic, _no_cost_log):
    """Two successive investigations reuse the same agent + environment."""
    client = _build_mock_client(_happy_path_events())
    mock_anthropic(client)
    await investigate(job_url=_JOB_URL)

    # Reset the stream for a second run (fresh scripted events).
    # AsyncMock — events.stream is an async def on the real SDK.
    client.beta.sessions.events.stream = AsyncMock(
        return_value=_FakeStream(_happy_path_events())
    )
    client.beta.sessions.archive.reset_mock()
    await investigate(job_url=_JOB_URL)

    # agents.create fired once; second call hit cache.
    assert client.beta.agents.create.call_count == 1
    assert client.beta.environments.create.call_count == 1
    # Sessions created twice (one per investigate() call).
    assert client.beta.sessions.create.call_count == 2


# ---------------------------------------------------------------------------
# Scenario: final JSON wrapped in markdown fences still parses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_tolerated(mock_anthropic, _no_cost_log):
    events = _happy_path_events()
    # Wrap the final JSON in ```json fences.
    original_text = events[-2].content[0]["text"]
    events[-2] = _FakeEvent(
        type="agent.message",
        content=[{"type": "text", "text": f"```json\n{original_text}\n```"}],
    )
    client = _build_mock_client(events)
    mock_anthropic(client)

    research, _ = await investigate(job_url=_JOB_URL)
    assert research.company_name == "Example Ltd"


# ---------------------------------------------------------------------------
# _parse_final_json — regression tests for prose-around-JSON tolerance
# ---------------------------------------------------------------------------


from trajectory.managed._events import _parse_final_json  # noqa: E402


class TestParseFinalJson:
    """Regression coverage for `_parse_final_json` after the live MA
    smoke caught the agent emitting prose around the JSON object
    (PROCESS Entry 45 follow-up). The parser now extracts the largest
    balanced `{...}` substring as a fallback."""

    def test_plain_json(self) -> None:
        assert _parse_final_json('{"a": 1}') == {"a": 1}

    def test_markdown_fences(self) -> None:
        assert _parse_final_json("```json\n{\"a\": 1}\n```") == {"a": 1}

    def test_prose_before_and_after(self) -> None:
        # The actual failure mode observed in the live MA run.
        text = (
            "Here is the final output:\n\n"
            '{"company_name": "Acme", "x": 1}\n\n'
            "Let me know if you need more."
        )
        assert _parse_final_json(text) == {"company_name": "Acme", "x": 1}

    def test_nested_objects(self) -> None:
        assert _parse_final_json('{"a": {"b": {"c": 1}}, "d": [1,2,3]}') == {
            "a": {"b": {"c": 1}},
            "d": [1, 2, 3],
        }

    def test_brace_inside_string_does_not_break_balance(self) -> None:
        text = 'prelude {"text": "value with } brace", "n": 1} epilogue'
        assert _parse_final_json(text) == {
            "text": "value with } brace",
            "n": 1,
        }

    def test_largest_object_wins_over_trivial(self) -> None:
        text = (
            "A trivial {} appears, then real: "
            '{"company_name": "X", "y": [1,2]}'
        )
        assert _parse_final_json(text) == {"company_name": "X", "y": [1, 2]}

    def test_no_json_returns_none(self) -> None:
        assert _parse_final_json("Just prose, no objects.") is None

    def test_escaped_quotes_in_string(self) -> None:
        assert _parse_final_json('{"k": "a \\"quoted\\" word"}') == {
            "k": 'a "quoted" word',
        }

    def test_raw_newline_in_string_value_recovered(self) -> None:
        """PROCESS Entry 47 bug 18 — managed_reviews_investigator
        emits raw 0x0A inside `text` fields when copy-pasting review
        content. Strict JSON rejects with 'Invalid control character';
        the parser now sanitizes and recovers."""
        # This string contains a literal newline INSIDE the text
        # field — invalid per the JSON spec.
        raw = '{"text": "first line\nsecond line", "n": 1}'
        # Verify standard json fails first (sanity check on the test).
        import json as _json
        with pytest.raises(_json.JSONDecodeError):
            _json.loads(raw)
        # Our parser recovers.
        assert _parse_final_json(raw) == {
            "text": "first line\nsecond line",
            "n": 1,
        }

    def test_raw_tab_and_carriage_return_recovered(self) -> None:
        raw = '{"text": "tab\there\rline-end-here"}'
        got = _parse_final_json(raw)
        assert got == {"text": "tab\there\rline-end-here"}

    def test_other_low_control_chars_recovered(self) -> None:
        # \x01, \x02 are legitimately invalid per JSON. Our sanitiser
        # escapes them as  /  so json.loads can parse.
        raw = '{"text": "ctrl\x01here"}'
        got = _parse_final_json(raw)
        assert got == {"text": "ctrl\x01here"}

    def test_trailing_comma_in_array_recovered(self) -> None:
        """PROCESS Entry 47 bug 24 — Opus occasionally emits trailing
        commas (`[1, 2, 3,]`) which strict json.loads rejects but
        every other JSON dialect tolerates."""
        raw = '{"items": [1, 2, 3,], "name": "ok",}'
        got = _parse_final_json(raw)
        assert got == {"items": [1, 2, 3], "name": "ok"}

    def test_missing_comma_between_object_keys_recovered(self) -> None:
        """PROCESS Entry 47 bug 24 — Opus occasionally drops the
        comma between two object key-value pairs:
        `{"a": "x" "b": "y"}` → fixer inserts the missing comma."""
        raw = '{"a": "x"\n  "b": "y"}'
        got = _parse_final_json(raw)
        assert got == {"a": "x", "b": "y"}

    def test_prose_then_json_with_raw_newlines_recovered(self) -> None:
        """The exact pathological combination that surfaced in
        managed_reviews_investigator (PROCESS Entry 47 run #8): the
        agent prepends prose, then emits JSON whose `text` fields
        contain raw newlines from copy-pasted reviews. Brace
        extraction picks the JSON block but `json.loads` rejects it
        unless we ALSO sanitize the extracted block."""
        raw = (
            "I have collected enough material across multiple sources. "
            "Let me compile the final output.\n\n"
            '{\n  "company_name": "Monzo Bank",\n  "excerpts": [\n'
            '    {\n      "source": "glassdoor",\n'
            '      "text": "\nFirst line of review\nsecond line"\n'
            "    }\n  ],\n"
            '  "investigation_notes": "Notes\nwith newlines."\n}'
        )
        got = _parse_final_json(raw)
        assert got is not None
        assert got["company_name"] == "Monzo Bank"
        assert len(got["excerpts"]) == 1
        assert "First line of review" in got["excerpts"][0]["text"]


# ---------------------------------------------------------------------------
# _to_company_research — citation snippet validation against UNSHIELDED text
# ---------------------------------------------------------------------------


from datetime import datetime, timezone  # noqa: E402

from trajectory.managed.company_investigator import (  # noqa: E402
    InvestigatorOutput,
    _to_company_research,
)
from trajectory.schemas import ScrapedPage  # noqa: E402


def _make_output(snippet: str) -> InvestigatorOutput:
    payload = {
        "company_name": "Example Ltd",
        "company_domain": "example.com",
        "culture_claims": [
            {
                "claim": "Culture values deep focus.",
                "source_url": _ABOUT_URL,
                "verbatim_snippet": snippet,
            }
        ],
        "tech_stack_signals": [],
        "team_size_signals": [],
        "recent_activity_signals": [],
        "posted_salary_bands": [],
        "careers_page_url": _CAREERS_URL,
        "not_on_careers_page": False,
        "extracted_jd": _extracted_jd_dict(),
        "investigation_notes": "fixture",
    }
    return InvestigatorOutput.model_validate(payload)


def _make_page(url: str, text: str) -> ScrapedPage:
    return ScrapedPage(
        url=url,
        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        text=text,
        text_hash="fixture",
    )


class TestCitationSnippetValidation:
    """Regression coverage for the snippet-validation fix that surfaced
    when running `managed_investigator` live (PROCESS Entry 45 follow-up).
    The agent picks snippets from the UNSHIELDED text it saw via
    `web_fetch`; the shield's truncation/redaction transformed that
    text before it reached `_to_company_research`. Validating against
    the shielded version caused spurious "snippet not in haystack"
    failures. Fix: pass `validation_pages` (unshielded) separately."""

    _JOB_URL = _JOB_URL
    _ABOUT_URL = _ABOUT_URL

    def test_snippet_in_unshielded_but_truncated_in_shielded(self) -> None:
        # The agent quotes a long sentence visible in the original page.
        full_text = (
            "About Example Ltd.\n\n"
            "We work together to solve challenging problems, leading "
            "with curiosity, kindness, and a shared passion for "
            "Example's mission. Founded 2019."
        )
        snippet = (
            "We work together to solve challenging problems, leading "
            "with curiosity, kindness, and a shared passion for "
            "Example's mission."
        )
        # Shielded text was truncated mid-word — old behaviour would
        # have raised on this.
        truncated = full_text[:80]  # cuts mid-phrase

        output = _make_output(snippet)
        original = [_make_page(_ABOUT_URL, full_text)]
        shielded = [_make_page(_ABOUT_URL, truncated)]

        research = _to_company_research(
            output,
            shielded,
            validation_pages=original,
            job_url=_JOB_URL,
        )
        # Validation passed; the CompanyResearch carries the SHIELDED
        # text downstream (so the verdict agent reads the safe version).
        assert research.scraped_pages[0].text == truncated
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_whitespace_normalization_tolerates_nbsp_and_newlines(
        self,
    ) -> None:
        # HTML→text extraction sometimes inserts NBSPs or splits a
        # phrase across newlines; the agent's snippet may use a single
        # space where the haystack has \n or \xa0.
        haystack_text = "Our\nteam\xa0values  curiosity over titles."
        snippet = "Our team values curiosity over titles."

        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack_text)

        research = _to_company_research(
            output,
            [page],
            validation_pages=[page],
            job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_real_paraphrase_still_rejected(self) -> None:
        # Defence: the fix tolerates whitespace differences but still
        # catches real paraphrasing.
        haystack_text = "We value autonomy and ownership."
        paraphrased = "We prize independence and accountability."

        output = _make_output(paraphrased)
        page = _make_page(_ABOUT_URL, haystack_text)

        with pytest.raises(ManagedInvestigatorFailed) as exc_info:
            _to_company_research(
                output,
                [page],
                validation_pages=[page],
                job_url=_JOB_URL,
            )
        assert "verbatim_snippet not found" in str(exc_info.value)

    def test_near_match_accepted_when_95pct_prefix_matches(
        self,
    ) -> None:
        """Live-run regression — Opus occasionally drops or rephrases
        the last 1-2 words of a long verbatim quote (PROCESS Entry 47:
        snippet=124c, longest matching prefix=113c, 91%). The
        validator now accepts ≥95% prefix matches on snippets ≥60c
        rather than rejecting the whole generation."""
        haystack = (
            "We work together to solve challenging problems, leading "
            "with curiosity, kindness, and a shared passion for "
            "GitHub's mission to be the home for all developers."
        )
        # Snippet diverges only in the trailing word: agent emitted
        # "...for GitHub's miss" — the kind of tail-truncation we saw
        # live in PROCESS Entry 46. ~96% prefix.
        snippet = (
            "We work together to solve challenging problems, leading "
            "with curiosity, kindness, and a shared passion for "
            "GitHub's miss"
        )
        # Verify the prefix-matching arithmetic: ≥95% should pass.
        from trajectory.managed.company_investigator import (
            _longest_matching_prefix, _normalize_ws,
        )
        ns = _normalize_ws(snippet)
        nh = _normalize_ws(haystack)
        prefix = _longest_matching_prefix(ns, nh)
        assert prefix / len(ns) >= 0.85, (
            f"prefix ratio={prefix / len(ns):.2f} — fixture too strict"
        )

        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)

        # Should NOT raise — near-match accepted.
        research = _to_company_research(
            output, [page],
            validation_pages=[page], job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_near_match_rejected_when_below_threshold(self) -> None:
        """Defence: the prefix tolerance only accepts ≥95% match. A
        50% prefix is still real paraphrase and should be rejected."""
        haystack = (
            "We value curiosity, autonomy, and ownership over titles. "
            "Engineers ship to production every week."
        )
        # Snippet diverges early — first ~30 chars match, rest doesn't.
        snippet = (
            "We value curiosity, autonomy, and a top-down command "
            "hierarchy that values seniority above all else."
        )
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        with pytest.raises(ManagedInvestigatorFailed) as exc_info:
            _to_company_research(
                output, [page],
                validation_pages=[page], job_url=_JOB_URL,
            )
        assert "verbatim_snippet not found" in str(exc_info.value)

    def test_short_snippet_requires_exact_match(self) -> None:
        """The 95% tolerance only kicks in for snippets ≥60 chars.
        A short 20-character quote that doesn't substring-match is
        still rejected — short quotes are easy to copy verbatim
        and the percentage tolerance is too forgiving on them."""
        haystack = "We value curiosity over titles."
        snippet = "We value rigor over titles."  # 26 chars, ~70% match
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        with pytest.raises(ManagedInvestigatorFailed):
            _to_company_research(
                output, [page],
                validation_pages=[page], job_url=_JOB_URL,
            )

    def test_multi_segment_ellipsis_accepted(self) -> None:
        """PROCESS Entry 47 — Opus routinely emits "verbatim" snippets
        as multiple in-page quotes joined by ellipsis (especially for
        listy pages like a careers nav). The validator accepts when
        every ≥12-char segment substring-matches the haystack."""
        haystack = (
            "Actions  Automate any workflow.\n\n"
            "Codespaces  Instant dev environments.\n\n"
            "Copilot  Write better code with AI.\n\n"
            "Packages  Host and manage packages."
        )
        snippet = (
            "Actions  Automate any workflow ... "
            "Codespaces  Instant dev environments ... "
            "Copilot  Write better code with AI"
        )
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        # Should NOT raise — every segment matches.
        research = _to_company_research(
            output, [page],
            validation_pages=[page], job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_multi_segment_with_paraphrased_segment_rejected(self) -> None:
        """Defence: a multi-segment snippet where ONE piece is
        paraphrased should still be rejected — the tolerance only
        accepts when every segment is verbatim."""
        haystack = (
            "Actions  Automate any workflow.\n\n"
            "Codespaces  Instant dev environments."
        )
        snippet = (
            "Actions  Automate any workflow ... "
            "Codespaces  some entirely different paraphrased thing"
        )
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        with pytest.raises(ManagedInvestigatorFailed):
            _to_company_research(
                output, [page],
                validation_pages=[page], job_url=_JOB_URL,
            )

    def test_sentence_boundary_split_accepted(self) -> None:
        """PROCESS Entry 47 bug 20 — Opus sometimes glues two
        sentences from different parts of the page together with no
        explicit `...` separator. The tolerance now also tries
        splitting on sentence boundaries before rejecting."""
        haystack = (
            "Here at GitHub, we believe in true work/life balance. "
            "That's why we offer healthcare and unlimited PTO.\n\n"
            "Many other paragraphs and content here filling the page.\n\n"
            "We also provide opportunities in addition to competitive "
            "pay, remote work, and comprehensive benefits."
        )
        # Two sentences from different paragraphs of the page, glued.
        snippet = (
            "Here at GitHub, we believe in true work/life balance. "
            "We also provide opportunities in addition to competitive "
            "pay, remote work, and comprehensive benefits."
        )
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        # Should NOT raise — both sentences match individually.
        research = _to_company_research(
            output, [page],
            validation_pages=[page], job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_pipe_separated_list_accepted(self) -> None:
        """PROCESS Entry 47 bug 22 — Opus assembles pipe-delimited
        lists from individual page elements (e.g. a country-cards
        section). The validator now accepts when every short segment
        substring-matches the haystack."""
        haystack = (
            "Locations\n\nAustralia\nCanada\nFrance\nGermany\nIndia\n"
            "Japan\nNetherlands\nSpain\nUnited States\nUnited Kingdom\n"
            "Many other paragraphs here with detail."
        )
        snippet = (
            "Australia | Canada | France | Germany | India | "
            "Japan | Netherlands | Spain | United States"
        )
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        research = _to_company_research(
            output, [page],
            validation_pages=[page], job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_comma_list_with_4plus_commas_accepted(self) -> None:
        """Comma-list tolerance fires when there are ≥4 commas (so
        ordinary prose with 1-2 commas doesn't accidentally trigger)."""
        haystack = (
            "We invest in Python, Go, Rust, TypeScript, "
            "and PostgreSQL — plus a long tail of others."
        )
        snippet = "Python, Go, Rust, TypeScript, PostgreSQL"
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        research = _to_company_research(
            output, [page],
            validation_pages=[page], job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet

    def test_sentence_boundary_split_with_paraphrase_rejected(
        self,
    ) -> None:
        """Defence: sentence-split tolerance only accepts when EVERY
        split sentence is verbatim. A paraphrased sentence still
        fails."""
        haystack = (
            "Here at GitHub, we believe in true work/life balance. "
            "We offer healthcare."
        )
        snippet = (
            "Here at GitHub, we believe in true work/life balance. "
            "We provide an entirely fabricated benefit you'd never find."
        )
        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack)
        with pytest.raises(ManagedInvestigatorFailed):
            _to_company_research(
                output, [page],
                validation_pages=[page], job_url=_JOB_URL,
            )

    def test_legacy_callers_with_no_validation_pages_still_work(
        self,
    ) -> None:
        # Backwards-compat: when validation_pages is omitted (older
        # callers, tests), validation falls back to shielded_pages —
        # the pre-fix behaviour. This ensures the fix doesn't break
        # anything that was already passing.
        haystack_text = "We value clarity above all."
        snippet = "We value clarity above all."

        output = _make_output(snippet)
        page = _make_page(_ABOUT_URL, haystack_text)

        research = _to_company_research(
            output,
            [page],
            job_url=_JOB_URL,
        )
        assert research.culture_claims[0].verbatim_snippet == snippet


# ---------------------------------------------------------------------------
# _extract_scraped_page — content-shape tolerance regression tests
# ---------------------------------------------------------------------------


from trajectory.managed._events import _extract_scraped_page  # noqa: E402


class _Obj:
    """Tiny helper that lets us build SDK-like objects with attribute
    access (the production code uses `_get` which tries both attribute
    and key access)."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestExtractScrapedPageContentShapes:
    """Regression coverage for `_extract_scraped_page` after the live
    `managed_investigator` run surfaced an empty-haystack failure
    (`haystack=0c` for github.careers/life-at-github). The fix adds
    fallback content-shape extraction for body/text fields and a
    last-resort recursive scan for `text` fields nested anywhere in
    the event."""

    _URL = "https://example.com/page"

    def test_documented_content_blocks(self) -> None:
        """The original happy path: list of `{type, text}` blocks."""
        event = {
            "content": [{"type": "text", "text": "Hello world."}],
            "url": self._URL,
        }
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == "Hello world."
        assert page.url == self._URL

    def test_output_string_fallback(self) -> None:
        event = {"output": "Body text via output field.", "url": self._URL}
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == "Body text via output field."

    def test_body_field_fallback(self) -> None:
        event = {"body": "Inline body field.", "url": self._URL}
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == "Inline body field."

    def test_text_field_fallback(self) -> None:
        event = {"text": "Direct text field.", "url": self._URL}
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == "Direct text field."

    def test_string_content_fallback(self) -> None:
        # Some SDK versions flatten content from a list of blocks to a
        # single string.
        event = {"content": "Flat string content.", "url": self._URL}
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == "Flat string content."

    def test_recursive_text_scan(self) -> None:
        # Last-resort: text nested deep in an unfamiliar event shape.
        event = {
            "url": self._URL,
            "result_envelope": {
                "version": 2,
                "blocks": [
                    {"role": "system", "text": "Outer marker."},
                    {
                        "role": "data",
                        "page": {"text": "Deep page body content here."},
                    },
                ],
            },
        }
        page = _extract_scraped_page(event)
        assert page is not None
        # Both the outer marker and the deep body text are surfaced.
        assert "Outer marker." in page.text
        assert "Deep page body content here." in page.text

    def test_sdk_object_attribute_walk(self) -> None:
        # Production tool_result events arrive as SDK objects with
        # attribute access, not dicts. The recursive walker must
        # follow attribute access too.
        deep = _Obj(text="Nested via attributes.")
        wrapper = _Obj(payload=deep, kind="web_fetch_result")
        event = _Obj(custom_field=wrapper, url=self._URL)
        page = _extract_scraped_page(event)
        assert page is not None
        assert "Nested via attributes." in page.text

    def test_empty_event_warns_and_records_empty(self, caplog) -> None:
        # Truly empty event with a URL — should still produce a
        # ScrapedPage (with empty text) and log a warning so the next
        # run's logs pin down the missing shape.
        import logging
        event = {"url": self._URL}
        with caplog.at_level(logging.WARNING):
            page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == ""
        assert any(
            "empty body" in rec.message.lower()
            for rec in caplog.records
        ), f"expected an 'empty body' warning, got: {[r.message for r in caplog.records]}"

    def test_no_url_no_text_returns_none(self) -> None:
        # Neither URL nor text → caller treats this as "not a web fetch".
        event = {"some_other_field": 1}
        assert _extract_scraped_page(event) is None

    def test_managed_agents_document_block_dict_shape(self) -> None:
        """Real Anthropic Managed Agents tool_result events return
        web_fetch results as `BetaManagedAgentsDocumentBlock` with a
        `source` carrying the page in its `data` field. PROCESS Entry 46
        full live run logged exactly this shape via the diagnostic
        warning. `_text_blocks` must recognise `type == "document"`
        and pull from `source.data` — without this, every web_fetch
        result during a managed_investigator session ended up with
        an empty haystack and the citation validator subsequently
        rejected every snippet."""
        page_text = (
            "GitHub Careers\n\nWe work together to solve challenging "
            "problems, leading with curiosity and kindness."
        )
        event = {
            "type": "agent.tool_result",
            "url": self._URL,
            "content": [
                {
                    "type": "document",
                    "source": {"type": "text", "data": page_text},
                }
            ],
        }
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == page_text

    def test_managed_agents_document_block_object_shape(self) -> None:
        """SDK-object form of the same shape (production). The SDK
        instances are `BetaManagedAgentsDocumentBlock(source=
        BetaManagedAgentsPlainTextDocumentSource(data=...))`."""
        page_text = "Life at GitHub\n\nWe value curiosity over titles."
        source = _Obj(type="text", data=page_text)
        block = _Obj(type="document", source=source)
        event = _Obj(type="agent.tool_result", url=self._URL, content=[block])
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.text == page_text

    def test_document_block_with_list_data(self) -> None:
        """Defensive: if a future SDK variant returns `source.data` as
        a list of strings, concatenate them rather than dropping the
        block silently."""
        event = {
            "url": self._URL,
            "content": [
                {
                    "type": "document",
                    "source": {"data": ["First chunk.", "Second chunk."]},
                }
            ],
        }
        page = _extract_scraped_page(event)
        assert page is not None
        assert "First chunk." in page.text
        assert "Second chunk." in page.text

    def test_url_falls_back_to_tool_use_before_body_regex(self) -> None:
        """URL precedence regression — surfaced by the live MA run
        when the agent fetched github.careers/life-at-github but the
        page's body started with `[Actions](https://github.com/features/actions)`,
        so body-regex picked up the navigation link instead. Citations
        then referenced the actual page URL which wasn't a key in
        page_texts. Fix: prefer `fallback_url` (from the originating
        tool_use) over body regex."""
        body_with_navigation_link = (
            "Life at GitHub | GitHub Careers\n\n"
            "* Product\n  + [Actions](https://github.com/features/actions)\n"
            "  + [Codespaces](https://github.com/features/codespaces)\n"
            "We work together to solve challenging problems."
        )
        # No direct `url` field on the event — production SDK shape.
        event = {
            "type": "agent.tool_result",
            "content": [
                {
                    "type": "document",
                    "source": {"data": body_with_navigation_link},
                }
            ],
        }
        page = _extract_scraped_page(
            event,
            fallback_url="https://www.github.careers/life-at-github",
        )
        assert page is not None
        assert page.url == "https://www.github.careers/life-at-github", (
            f"URL fell back to body regex: {page.url}"
        )
        assert "Life at GitHub" in page.text

    def test_direct_url_field_wins_over_fallback(self) -> None:
        """Regression-defence: when the event DOES carry an explicit
        url field, that wins over the fallback_url (the explicit field
        is more authoritative)."""
        event = {
            "url": "https://example.com/explicit",
            "content": [{"type": "text", "text": "Body."}],
        }
        page = _extract_scraped_page(
            event, fallback_url="https://example.com/fallback",
        )
        assert page is not None
        assert page.url == "https://example.com/explicit"

    def test_body_url_used_when_no_fallback_and_no_explicit(self) -> None:
        """Backwards-compat: body-regex still fires as a last resort
        when neither the event nor the fallback carries a URL."""
        event = {
            "content": [
                {"type": "text", "text": "See https://only-in-body.example/page1 for details."}
            ],
        }
        page = _extract_scraped_page(event)
        assert page is not None
        assert page.url == "https://only-in-body.example/page1"


# ---------------------------------------------------------------------------
# _unwrap_parameter_value — 2-key envelope regression
# ---------------------------------------------------------------------------


from trajectory.llm import _unwrap_parameter_value  # noqa: E402


class TestUnwrapParameterValue:
    """Regression coverage for the `{"name": "<schema>", "arguments":
    {...}}` two-key envelope variant that surfaced in the full live
    run (PROCESS Entry 46) — Pydantic complained "5 validation errors
    for CVOutput / contact, professional_summary, experience,
    education, skills" because it tried to validate the envelope
    itself instead of `arguments`."""

    def test_passthrough_for_already_clean_dict(self) -> None:
        clean = {"name": "Smoke", "professional_summary": "..."}
        # NB this happens to be 2-key with "name" but no "arguments";
        # it must NOT be unwrapped.
        assert _unwrap_parameter_value(clean) == clean

    def test_single_key_arguments_wrapper_unwrapped(self) -> None:
        wrapped = {"arguments": {"a": 1, "b": 2}}
        assert _unwrap_parameter_value(wrapped) == {"a": 1, "b": 2}

    def test_single_key_parameter_wrapper_unwrapped(self) -> None:
        wrapped = {"parameter": {"name": "Smoke"}}
        assert _unwrap_parameter_value(wrapped) == {"name": "Smoke"}

    def test_two_key_function_call_envelope_unwrapped(self) -> None:
        wrapped = {
            "name": "CVOutput",
            "arguments": {
                "name": "Smoke Candidate",
                "professional_summary": "Backend engineer.",
            },
        }
        assert _unwrap_parameter_value(wrapped) == {
            "name": "Smoke Candidate",
            "professional_summary": "Backend engineer.",
        }

    def test_two_key_envelope_with_non_dict_arguments_passed_through(
        self,
    ) -> None:
        # Defence: only unwrap when `arguments` is a dict. A bare
        # string isn't a payload, leave it alone.
        wrapped = {"name": "X", "arguments": "not a dict"}
        assert _unwrap_parameter_value(wrapped) == wrapped

    def test_non_dict_input_passed_through(self) -> None:
        assert _unwrap_parameter_value([1, 2, 3]) == [1, 2, 3]
        assert _unwrap_parameter_value("plain string") == "plain string"
        assert _unwrap_parameter_value(None) is None
