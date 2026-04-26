"""Smoke test — bot read-only intents (`profile_query`, `recent`).

The two read-only Telegram intents at [bot/handlers.py:565,578]
([_handle_profile_query], [_handle_recent]) had no test coverage —
they're demo-facing read commands and a silent regression here would
show up as broken replies on stage. This smoke seeds storage with
realistic content, drives each handler with a mocked `Update` /
`context`, and asserts the reply-text shape.

Cost: $0 (no LLM calls, no network).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    prepare_environment,
    run_smoke,
)

NAME = "bot_read_intents"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


def _make_update(*, user_id: str, chat_id: int, text: str):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.document = None
    update.message.reply_text = AsyncMock()
    update.message.reply_html = AsyncMock()
    return update


def _make_context(storage):
    ctx = MagicMock()
    ctx.bot_data = {"storage": storage}
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    messages: list[str] = []
    failures: list[str] = []

    from trajectory.bot import handlers as bot_handlers
    from trajectory.schemas import CareerEntry, Verdict, ReasoningPoint, Citation, MotivationFitReport
    from trajectory.storage import Storage

    user = build_test_user("uk_resident")
    storage = Storage()
    await storage.initialise()
    await storage.save_user_profile(user)

    # Seed enough variety to exercise both intents.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seeds = [
        ("conversation", "Seven years backend Python + Go at two payments companies."),
        ("motivation", "Want to ship products real users rely on, not pure maintenance."),
        ("motivation", "Engineers in leadership positions; public engineering blog."),
        ("deal_breaker", "Five-day office mandates are a no for me."),
        ("good_role_signal", "Strong engineering culture with real autonomy."),
    ]
    for kind, text in seeds:
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user.user_id,
            kind=kind,
            raw_text=text,
            created_at=now,
        ))

    # ── 1. profile_query ──────────────────────────────────────────────
    update = _make_update(
        user_id=user.user_id, chat_id=999_900_010,
        text="What are my motivations again?",
    )
    ctx = _make_context(storage)

    try:
        await bot_handlers._handle_profile_query(update, ctx, user, storage)
    except Exception as exc:
        failures.append(f"_handle_profile_query raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    if update.message.reply_text.await_count == 0:
        failures.append(
            "_handle_profile_query did not call reply_text — "
            "even an empty-profile path should reply."
        )
    else:
        body = update.message.reply_text.await_args.args[0]
        # The handler joins entries as "• kind: snippet" lines.
        if not isinstance(body, str) or "•" not in body:
            failures.append(
                f"profile_query reply not bullet-formatted: {body!r}"
            )
        else:
            messages.append(
                f"profile_query: {body.count(chr(10)) + 1} bullet line(s) "
                f"surfaced from {len(seeds)} seeded entries"
            )

    # ── 2. recent — seed sessions (with one verdict) and call ─────────
    sess1 = build_test_session(user.user_id, intent="forward_job")
    sess1.job_url = "https://example.com/job/alpha"
    await storage.save_session(sess1)
    sess2 = build_test_session(user.user_id, intent="forward_job")
    sess2.job_url = "https://example.com/job/beta"
    await storage.save_session(sess2)
    # Attach a verdict to sess2 so the reply formatter has a decision
    # to surface — exercises the `s.verdict` branch in _handle_recent.
    citation = Citation(
        kind="url_snippet",
        url="https://example.com/job/beta",
        verbatim_snippet="Senior Software Engineer",
    )
    verdict = Verdict(
        decision="GO",
        confidence_pct=80,
        headline="Apply - sponsor + salary clear.",
        reasoning=[
            ReasoningPoint(
                claim="Synthetic claim for recent test.",
                supporting_evidence="fixture",
                citation=citation,
            )
        ] * 3,
        hard_blockers=[],
        stretch_concerns=[],
        motivation_fit=MotivationFitReport(
            motivation_evaluations=[],
            deal_breaker_evaluations=[],
            good_role_signal_evaluations=[],
        ),
    )
    await storage.save_verdict(sess2.session_id, verdict)

    update2 = _make_update(
        user_id=user.user_id, chat_id=999_900_010, text="recent",
    )
    ctx2 = _make_context(storage)

    try:
        await bot_handlers._handle_recent(update2, ctx2, user, storage)
    except Exception as exc:
        failures.append(f"_handle_recent raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    if update2.message.reply_text.await_count == 0:
        failures.append("_handle_recent did not call reply_text")
    else:
        body = update2.message.reply_text.await_args.args[0]
        if not isinstance(body, str):
            failures.append(f"recent reply not a str: {type(body)}")
        elif "example.com/job/" not in body:
            failures.append(
                f"recent reply missing job URLs: {body!r}"
            )
        elif "GO" not in body:
            failures.append(
                "recent reply missing the GO decision tag from sess2's verdict"
            )
        else:
            line_count = body.count("\n") + 1
            messages.append(
                f"recent: {line_count} line(s); GO decision surfaced for sess2"
            )

    await storage.close()
    return messages, failures, ESTIMATED_COST_USD


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
