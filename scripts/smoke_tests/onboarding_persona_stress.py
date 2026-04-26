"""Onboarding persona stress smoke — 20 user variations.

Iterates [PERSONAS] from `onboarding_personas.py` and POSTs each to
`/api/onboarding/finalise`, asserting the resulting profile matches
the persona's `expected` block. Exercises:

  - UK resident vs visa_holder branching (10 each)
  - Tech vs non-tech career narratives (3 PM/designer/ops)
  - Vague answers → raw-text fallback when the parser returns empty
  - Adversarial input → Tier 1 Content Shield redaction in motivations
    + writing samples
  - Edge cases: zero writing samples → no style profile;
    over-cap input → truncation marker doesn't break the parser.

Cost: $0 (style_extractor + parse_stage both patched to fixtures
that mirror the real LLM output shape — vague inputs return parsed
results with empty lists so the orchestrator's raw-text fallback
fires; adversarial inputs return parsed results since the LLM
parser would too — the redaction we assert is from Tier 1 of the
Content Shield which IS exercised live).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ._common import (
    SmokeResult,
    prepare_environment,
    run_smoke,
)
from .onboarding_personas import PERSONAS

NAME = "onboarding_persona_stress"
REQUIRES_LIVE_LLM = False
ESTIMATED_COST_USD = 0.0


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from fastapi.testclient import TestClient
    from trajectory.api.app import create_app
    from trajectory.api.routes import onboarding as onboarding_route
    from trajectory.config import settings
    from trajectory.schemas import (
        DealBreakersParseResult,
        MotivationsParseResult,
        WritingStyleProfile,
    )
    from trajectory.sub_agents import onboarding_parser, style_extractor
    from trajectory.storage import Storage

    messages: list[str] = []
    failures: list[str] = []

    # Patch the LLM-backed pieces with fixtures that respond to the
    # input. For motivations / deal_breakers, we return a parsed list
    # split on sentence-final punctuation IF the input has 3+ words —
    # otherwise we return empty lists so the orchestrator's raw-text
    # fallback fires (matching the live LLM's "needs_clarification"
    # behaviour on minimal input).
    original_extract = style_extractor.extract
    original_parse_stage = onboarding_parser.parse_stage
    original_route_extract = getattr(onboarding_route, "extract_style", None)

    def _split_sentences(text: str) -> list[str]:
        import re
        # Lightweight sentence split. Don't over-engineer — the smoke is
        # asserting on count, not content quality.
        sents = re.split(r"(?<=[.!?])\s+", text.strip())
        return [s.strip() for s in sents if len(s.strip()) > 5]

    async def _fake_extract(*, user_id, samples):
        return WritingStyleProfile(
            profile_id=f"smoke_persona_{user_id}_style",
            user_id=user_id,
            tone="plainspoken, technical",
            sentence_length_pref="varied",
            formality_level=6,
            hedging_tendency="direct",
            signature_patterns=[],
            avoided_patterns=[],
            examples=[],
            source_sample_ids=[f"sample_{i}" for i in range(len(samples))],
            sample_count=len(samples),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    # Mirror the production parse_stage flow: shield first (Tier 1 +
    # Tier 2 if flagged for high-stakes agents — onboarding_parser is
    # low-stakes so just Tier 1), THEN parse. Production runs the
    # shield inside `_call_parser`; mocking parse_stage means we have
    # to run the shield ourselves so adversarial input gets redacted
    # before it reaches the parsed lists. Without this the test
    # mocks away the very thing we want to verify.
    from trajectory.validators.content_shield import shield as shield_content

    async def _fake_parse_stage(stage: str, user_text: str):
        cleaned, _verdict = await shield_content(
            content=user_text,
            source_type="user_message",
            downstream_agent="onboarding_parser",
        )
        if stage == "motivations":
            sents = _split_sentences(cleaned)
            if len(sents) < 2:
                return MotivationsParseResult(
                    status="needs_clarification",
                    motivations=[],
                    drains=[],
                )
            half = max(1, len(sents) // 2)
            return MotivationsParseResult(
                status="parsed",
                motivations=sents[:half],
                drains=sents[half:],
            )
        if stage == "deal_breakers":
            sents = _split_sentences(cleaned)
            if len(sents) < 1:
                return DealBreakersParseResult(
                    status="needs_clarification",
                    deal_breakers=[],
                    good_role_signals=[],
                )
            return DealBreakersParseResult(
                status="parsed",
                deal_breakers=sents,
                good_role_signals=[],
            )
        return None

    style_extractor.extract = _fake_extract
    onboarding_parser.parse_stage = _fake_parse_stage
    if original_route_extract is not None:
        onboarding_route.extract_style = _fake_extract

    # Track stats per category so the rollup tells us which slice broke.
    by_cat: dict[str, dict[str, int]] = {}

    try:
        for persona in PERSONAS:
            cat = persona["category"]
            by_cat.setdefault(cat, {"pass": 0, "fail": 0})
            user_id = f"smoke_persona_{persona['id']}"
            settings.demo_user_id = user_id

            # The TestClient context cleans the FastAPI app each iteration —
            # important so storage state from one persona doesn't bleed into
            # the next assertion. The shared SQLite tempdir is fine since
            # we key everything by user_id.
            app = create_app()
            try:
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/onboarding/finalise",
                        json=persona["payload"],
                    )
                    if resp.status_code != 201:
                        failures.append(
                            f"[{persona['id']}] finalise -> {resp.status_code}: "
                            f"{resp.text[:200]!r}"
                        )
                        by_cat[cat]["fail"] += 1
                        continue

                    body = resp.json()
                    expected = persona["expected"]
                    persona_failures: list[str] = []

                    # ── Style profile expectation ────────────────────
                    has_style = body.get("writing_style_profile_id") is not None
                    if expected.get("needs_style_profile") and not has_style:
                        persona_failures.append(
                            "expected style profile but got None"
                        )
                    if (
                        not expected.get("needs_style_profile")
                        and has_style
                    ):
                        persona_failures.append(
                            "got style profile when expected None "
                            "(empty writing_samples)"
                        )

                    # ── Career-entry count ──────────────────────────
                    if (
                        body["career_entries_written"]
                        < expected["min_career_entries"]
                    ):
                        persona_failures.append(
                            f"career_entries_written="
                            f"{body['career_entries_written']} "
                            f"< {expected['min_career_entries']}"
                        )

                    # ── Profile reload + branch checks ──────────────
                    presp = client.get("/api/profile")
                    if presp.status_code != 200:
                        persona_failures.append(
                            f"GET /api/profile -> {presp.status_code}"
                        )
                    else:
                        profile = presp.json()

                        if profile["user_type"] != expected["user_type"]:
                            persona_failures.append(
                                f"user_type={profile['user_type']!r} "
                                f"!= expected {expected['user_type']!r}"
                            )

                        if expected["user_type"] == "visa_holder":
                            vs = profile.get("visa_status") or {}
                            if vs.get("route") != expected.get("visa_route"):
                                persona_failures.append(
                                    f"visa_status.route="
                                    f"{vs.get('route')!r} != "
                                    f"{expected.get('visa_route')!r}"
                                )
                        else:
                            if profile.get("visa_status") not in (None, {}):
                                persona_failures.append(
                                    f"uk_resident but visa_status="
                                    f"{profile.get('visa_status')!r}"
                                )

                        if (
                            len(profile["motivations"])
                            < expected["min_motivations"]
                        ):
                            persona_failures.append(
                                f"motivations count="
                                f"{len(profile['motivations'])} "
                                f"< {expected['min_motivations']}"
                            )

                        # Adversarial: Tier 1 redaction should have
                        # stripped the role-flip / im_start markers
                        # from any text that ends up on the profile.
                        if expected.get("expects_redaction_in_motivations"):
                            joined = " ".join(profile["motivations"]) + " " + " ".join(profile["deal_breakers"])
                            if (
                                "<|im_start|>" in joined
                                or "[SYSTEM]" in joined
                                or "ignore previous instructions"
                                    in joined.lower()
                            ):
                                persona_failures.append(
                                    "Tier 1 redaction missed an "
                                    "injection marker in motivations / "
                                    "deal_breakers"
                                )

                    # ── Adversarial: writing samples should have been
                    # cleaned by Tier 1 before they were written as
                    # CareerEntry rows. Best signal: retrieve them and
                    # check no `<|im_start|>` survives.
                    if expected.get("expects_redaction_in_samples"):
                        storage = Storage()
                        await storage.initialise()
                        try:
                            entries = await storage.retrieve_relevant_entries(
                                user_id=user_id,
                                query="writing samples",
                                k=10,
                            )
                            sample_text = "\n".join(
                                e.raw_text for e in entries
                                if e.kind == "writing_sample"
                            )
                            if "<|im_start|>" in sample_text:
                                persona_failures.append(
                                    "Tier 1 redaction missed "
                                    "<|im_start|> in writing samples"
                                )
                        finally:
                            await storage.close()

                    # ── FAISS sanity: every persona should have at
                    # least one retrievable career entry by the time
                    # finalise returns. Skip for the empty-samples /
                    # vague edge cases where we expect minimal data.
                    if persona["id"] not in {
                        "vague_minimal", "vague_one_word_per_field",
                        "edge_empty_writing_samples",
                    }:
                        storage = Storage()
                        await storage.initialise()
                        try:
                            retrieved = (
                                await storage.retrieve_relevant_entries(
                                    user_id=user_id,
                                    query=(
                                        persona["payload"]["motivations_text"]
                                        or "career"
                                    )[:200],
                                    k=8,
                                )
                            )
                            if not retrieved:
                                persona_failures.append(
                                    "FAISS retrieval returned 0 entries"
                                )
                        finally:
                            await storage.close()

                    if persona_failures:
                        for pf in persona_failures:
                            failures.append(f"[{persona['id']}] {pf}")
                        by_cat[cat]["fail"] += 1
                    else:
                        by_cat[cat]["pass"] += 1
            except Exception as exc:
                failures.append(f"[{persona['id']}] raised: {exc!r}")
                by_cat[cat]["fail"] += 1
    finally:
        style_extractor.extract = original_extract
        onboarding_parser.parse_stage = original_parse_stage
        if original_route_extract is not None:
            onboarding_route.extract_style = original_route_extract

    # Per-category rollup → easy diagnose-by-slice.
    total_pass = sum(c["pass"] for c in by_cat.values())
    total_fail = sum(c["fail"] for c in by_cat.values())
    messages.append(
        f"persona stress: {total_pass}/{total_pass + total_fail} "
        f"across {len(PERSONAS)} fixtures"
    )
    for cat in sorted(by_cat):
        c = by_cat[cat]
        total = c["pass"] + c["fail"]
        marker = "ok" if c["fail"] == 0 else f"{c['fail']} FAIL"
        messages.append(f"  {cat:<12} {c['pass']}/{total}  [{marker}]")

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
