"""Live smoke — multi-provider CV tailor (PROCESS Entry 44).

Calls `cv_tailor_multi_provider.generate_via_provider` once per non-
Anthropic provider against the fixture bundle + a synthetic career
history. Verifies each adapter produces a valid CVOutput.

Per-provider live verification:
  - openai  (~$0.05-0.15)
  - cohere  (~$0.05-0.15)
  - anthropic — skipped here; covered by the existing phase4_cv smoke.

Total cost: ~$0.20 for the two non-Anthropic adapters.

Llama support was removed 2026-04-26 (only Crelate routed there;
reassigned to Anthropic) — see PROCESS Entry 44 amendment.

Each provider's failure is reported individually so a single broken key
or model id doesn't mask the others.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from ._common import (
    SmokeResult,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    run_smoke,
)

NAME = "multi_provider_cv_tailor_live"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.20


_PROVIDERS_TO_TEST: list[tuple[str, str]] = [
    # (provider name, the env var that must be set for it to run)
    ("openai", "OPENAI_API_KEY"),
    ("cohere", "COHERE_API_KEY"),
]


async def _seed_career_entries(storage, user_id: str) -> int:
    """Without ≥3 career entries the agent has nothing to cite. Seed
    a small synthetic history so the post-validator's career_entry
    citation rules can pass."""
    from trajectory.schemas import CareerEntry

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seeds = [
        ("project_note", "Built a distributed payments pipeline on Kubernetes handling 1M RPS; cut p99 latency from 600ms to 195ms via parallel validators + LRU cache + connection-pool tuning."),
        ("project_note", "Migrated 50M-row Postgres database to CockroachDB across a six-week zero-downtime cutover; wrote the runbook + on-call pager rotation."),
        ("star_polish", "After a payments outage that dropped 0.4% of transactions for 18 minutes, led the blameless postmortem and shipped circuit-breaker + bulkhead patterns into the order service."),
        ("project_note", "Owned the typed Python SDK refactor (Pydantic v2 + mypy strict + ruff): 14 services, 800+ public functions, six-month migration with zero customer-visible breakage."),
        ("conversation", "Eight years backend Python + Go. Last role: tech lead, four-person platform team. Comfortable in the data path: PostgreSQL, Kafka, Kubernetes, AWS."),
        ("qa_answer", "When asked about a hard incident I describe the November 2024 payments-pipeline outage: the trigger was a Postgres VACUUM stall during a deploy; mitigation was a connection-pool resize + a follow-up cap on autovacuum cost."),
    ]
    for kind, text in seeds:
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind=kind,
            raw_text=text,
            created_at=now,
        ))
    return len(seeds)


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.config import settings
    from trajectory.storage import Storage
    from trajectory.sub_agents import cv_tailor_multi_provider as cv_mp
    from trajectory.schemas import CVOutput, WritingStyleProfile

    messages: list[str] = []
    failures: list[str] = []
    actual_cost = 0.0

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")

    storage = Storage()
    await storage.initialise()
    await storage.save_user_profile(user)
    seeded = await _seed_career_entries(storage, user.user_id)
    messages.append(f"seeded {seeded} synthetic career entries")

    style_profile = WritingStyleProfile(
        profile_id=f"smoke_{user.user_id}",
        user_id=user.user_id,
        tone="plainspoken, technical",
        sentence_length_pref="varied",
        formality_level=6,
        hedging_tendency="direct",
        signature_patterns=["leads with the result", "uses numbers not adjectives"],
        avoided_patterns=["buzzwords", "vague corporate speak"],
        examples=[
            "Cut p99 from 600ms to 195ms.",
            "Owned the Postgres → CockroachDB migration end-to-end.",
        ],
        source_sample_ids=["s1", "s2", "s3"],
        sample_count=3,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    # Per-provider cost ceiling for the budget gate.
    per_provider_budget = {
        "openai": 0.20,
        "cohere": 0.20,
    }

    for provider, key_env in _PROVIDERS_TO_TEST:
        # Skip if no key — report rather than fail.
        if not getattr(settings, f"{provider}_api_key", "") and not os.getenv(key_env):
            messages.append(f"{provider}: SKIPPED (no {key_env} in env)")
            continue

        msg_prefix = f"{provider}: "
        try:
            # Reset module-level cost before each provider so we can
            # isolate the spend.
            from trajectory.storage import total_cost_usd
            cost_before = await total_cost_usd()

            cv: CVOutput = await cv_mp.generate_via_provider(
                provider=provider,  # type: ignore[arg-type]
                jd=bundle.extracted_jd,
                research_bundle=bundle,
                user=user,
                style_profile=style_profile,
                star_material=None,
                citation_ctx=None,  # validation logged but not enforced (parity with multi-provider path)
                session_id=f"smoke-{provider}",
            )

            cost_after = await total_cost_usd()
            this_call = cost_after - cost_before
            actual_cost += this_call

            roles = len(cv.experience)
            bullets = sum(len(r.bullets) for r in cv.experience)
            messages.append(
                f"{msg_prefix}OK roles={roles} bullets={bullets} "
                f"cost=${this_call:.4f}"
            )
            if roles == 0:
                failures.append(f"{provider}: zero roles in CVOutput")
            if bullets == 0:
                failures.append(f"{provider}: zero bullets across all roles")
            if this_call > per_provider_budget.get(provider, 0.50):
                failures.append(
                    f"{provider}: cost ${this_call:.4f} exceeded budget "
                    f"${per_provider_budget.get(provider, 0.50):.2f}"
                )

        except Exception as exc:
            # User-side billing/quota issues report as skips, not
            # failures — the code path executed correctly; the upstream
            # provider rejected the request for non-code reasons.
            err_text = str(exc).lower()
            is_billing = (
                "credit_limit" in err_text
                or "credit limit" in err_text
                or "insufficient_quota" in err_text
                or "billing" in err_text
                or " 402" in err_text
                or " 429" in err_text
            )
            if is_billing:
                messages.append(
                    f"{msg_prefix}SKIPPED (provider billing/quota): "
                    f"{type(exc).__name__}: {str(exc)[:160]}"
                )
            else:
                failures.append(f"{msg_prefix}{type(exc).__name__}: {exc}")

    await storage.close()
    return messages, failures, actual_cost


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    asyncio.run(run())
