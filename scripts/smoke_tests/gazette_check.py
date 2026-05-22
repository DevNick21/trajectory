"""Smoke: The Gazette insolvency-notice parser.

Two layers:

  1. Offline (always-on, free) — fixture-driven assertions that lock in
     the API contract we verified live on 2026-05-22:
       * Envelope key is `entry` (singular), not `notices`/`items`.
       * `content` is escaped HTML, not pre-stripped text.
       * Notice type is encoded as a phrase inside the body, not a
         top-level `notice-code` field.
       * Bundled supplements lump many companies into one entry.
     Any future drift in our parser (or accidental refactor of the
     classifier) trips this layer.

  2. Live (gated by SMOKE_GAZETTE_LIVE=1, free — no API key) — hits
     thegazette.co.uk once with `service=insolvency` and asserts the
     parser returns a parseable signal for a known insolvent target.
     Skipped by default so the cheap tier stays hermetic.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "gazette_check"
ESTIMATED_COST_USD = 0.0


# Minimal envelope mirroring the real Gazette response shape. The bodies
# are abridged but preserve the phrase-classification surface we depend on.
_FIXTURE_ENVELOPE = {
    "f:total": 2,
    "entry": [
        {
            "id": "https://www.thegazette.co.uk/notice/4500001",
            "title": "The London Gazette, Issue 99999, Page 1",
            "published": "2025-09-15T00:00:00",
            "updated": "2025-09-15T00:00:00",
            "link": [
                {"@href": "/notice/4500001/data.pdf", "@rel": "self"},
            ],
            "content": (
                "<div>In the High Court of Justice. "
                "ACME WIDGETS LIMITED (in Administration). "
                "Company Number 09563205. "
                "Notice is hereby given of the appointment of joint "
                "administrators of the above-named Company on 1 "
                "September 2025.</div>"
            ),
        },
        {
            "id": "https://www.thegazette.co.uk/notice/4500002",
            "title": "The London Gazette, Issue 99999, Page 2",
            "published": "2025-10-01T00:00:00",
            "updated": "2025-10-01T00:00:00",
            "link": [
                {"@href": "/notice/4500002/data.pdf", "@rel": "self"},
            ],
            "content": (
                "<div>Notices of intent to strike off. "
                "ALPHA HOLDINGS LIMITED 11111111 "
                "BETA TRADING LIMITED 22222222 "
                "GAMMA CO LIMITED 33333333.</div>"
            ),
        },
    ],
}


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()
    messages: list[str] = []
    failures: list[str] = []

    from askpicky.sub_agents import gazette_check as gc

    # ── Layer 1: offline parsing ──────────────────────────────────────

    entries = gc._entries(_FIXTURE_ENVELOPE)
    if len(entries) != 2:
        failures.append(f"expected 2 entries, got {len(entries)}")
        return messages, failures, ESTIMATED_COST_USD

    # Entry 0 — explicit administrator-appointment phrase.
    parsed = gc._parse_entry(entries[0])
    if not parsed:
        failures.append("_parse_entry returned None for administrator notice")
        return messages, failures, ESTIMATED_COST_USD
    sig0, body0 = parsed
    if sig0.notice_code != "2410":
        failures.append(
            f"administrator notice classified as {sig0.notice_code!r}; "
            f"expected '2410'"
        )
    if sig0.published_at != date(2025, 9, 15):
        failures.append(
            f"published_at = {sig0.published_at}; expected 2025-09-15"
        )
    if "ACME WIDGETS" not in (sig0.company_name_on_notice or ""):
        failures.append(
            f"company_name_on_notice = {sig0.company_name_on_notice!r}; "
            f"expected to contain 'ACME WIDGETS'"
        )
    else:
        messages.append(
            f"administrator notice: code={sig0.notice_code} "
            f"company={sig0.company_name_on_notice!r}"
        )

    # Entry 1 — bundled strike-off supplement. No specific phrase, so it
    # should classify as the generic 2400 code.
    parsed = gc._parse_entry(entries[1])
    if not parsed:
        failures.append("_parse_entry returned None for bundled supplement")
    else:
        sig1, body1 = parsed
        if sig1.notice_code != gc._GENERIC_INSOLVENCY_CODE:
            failures.append(
                f"bundled supplement classified as {sig1.notice_code!r}; "
                f"expected generic {gc._GENERIC_INSOLVENCY_CODE!r}"
            )
        else:
            messages.append(
                f"bundled supplement: code={sig1.notice_code} "
                f"(correctly generic)"
            )

        # CRN-anchored matching must scope to the right company. Querying
        # for the trading entity 22222222 should match; an unrelated CRN
        # 99999999 must not.
        matched_correct = gc._matches_target(
            sig1,
            raw_notice_text=body1,
            query_terms=["BETA TRADING LIMITED"],
            crn="22222222",
        )
        matched_wrong = gc._matches_target(
            sig1,
            raw_notice_text=body1,
            query_terms=["UNRELATED CO LIMITED"],
            crn="99999999",
        )
        if not matched_correct:
            failures.append(
                "CRN 22222222 not matched in bundled body containing it"
            )
        elif matched_wrong:
            failures.append(
                "CRN 99999999 wrongly matched a bundle that doesn't list it"
            )
        else:
            messages.append("CRN-anchored matching: precise scoping confirmed")

    # ── Hard-blocker contract ─────────────────────────────────────────

    expected_blockers = {"2410", "2440", "2441", "2450", "2451"}
    if gc.HARD_BLOCKER_CODES != expected_blockers:
        failures.append(
            f"HARD_BLOCKER_CODES drifted: {gc.HARD_BLOCKER_CODES}"
        )
    else:
        messages.append(
            f"hard-blocker codes locked: {sorted(gc.HARD_BLOCKER_CODES)}"
        )

    # Generic 2400 must NOT trigger has_hard_blocker — that's the whole
    # point of separating it out (bundled supplements are noisy).
    fake_generic = gc.GazetteSignal(
        notice_code=gc._GENERIC_INSOLVENCY_CODE,
        notice_type=gc._GENERIC_INSOLVENCY_LABEL,
        published_at=date.today(),
        active=True,
    )
    if gc.has_hard_blocker([fake_generic]) is not None:
        failures.append(
            "has_hard_blocker fired on generic 2400 — bundled-supplement "
            "noise would cause false NO_GO verdicts"
        )
    else:
        messages.append("generic 2400 correctly NOT a hard blocker")

    # And one of the strong codes MUST trigger.
    fake_petition = gc.GazetteSignal(
        notice_code="2450",
        notice_type="Winding-Up Petition",
        published_at=date.today(),
        active=True,
    )
    if gc.has_hard_blocker([fake_petition]) is None:
        failures.append(
            "has_hard_blocker did not fire on 2450 — winding-up petition "
            "is the strongest pre-failure signal"
        )
    else:
        messages.append("2450 winding-up petition correctly triggers blocker")

    # ── Recency cut-off ───────────────────────────────────────────────

    # Build an envelope dated 5 years ago and confirm `check()` drops it
    # after the recency filter.
    old_date_iso = (date.today() - timedelta(days=365 * 5)).isoformat() + "T00:00:00"
    old_envelope = {
        "f:total": 1,
        "entry": [
            {
                "id": "https://www.thegazette.co.uk/notice/historic",
                "published": old_date_iso,
                "link": [{"@href": "/notice/historic/data.pdf"}],
                "content": (
                    "<div>HISTORIC CO LIMITED Company Number 12345678. "
                    "Notice of appointment of administrators dated 2020.</div>"
                ),
            },
        ],
    }

    async def _fake_search(name: str, **_kw):
        return old_envelope

    original_search = gc._search
    gc._search = _fake_search  # type: ignore[assignment]
    try:
        results = await gc.check(
            company_name="HISTORIC CO LIMITED",
            canonical_name="HISTORIC CO LIMITED",
            crn="12345678",
        )
    finally:
        gc._search = original_search  # type: ignore[assignment]
    if results:
        failures.append(
            f"recency cut-off failed: {len(results)} 5-year-old notice(s) "
            f"surfaced"
        )
    else:
        messages.append("recency cut-off OK: 5-year-old notice dropped")

    # ── Layer 2: optional live network probe ─────────────────────────

    if os.environ.get("SMOKE_GAZETTE_LIVE") == "1":
        try:
            live = await gc.check(
                company_name="WILKO LIMITED",
                canonical_name="WILKO LIMITED",
                crn="00365335",
            )
            messages.append(
                f"live: {len(live)} signal(s) for WILKO LIMITED (CRN 00365335)"
            )
        except Exception as exc:
            failures.append(f"live Gazette probe raised: {exc!r}")
    else:
        messages.append(
            "live probe skipped (set SMOKE_GAZETTE_LIVE=1 to enable)"
        )

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
