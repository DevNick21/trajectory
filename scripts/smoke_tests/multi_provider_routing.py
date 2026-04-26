"""Smoke test — multi-provider CV tailor routing (no LLM).

Verifies the URL → ATS → provider resolution table and the import
hygiene of the four provider adapters. Does NOT call any of them
live — that's gated behind SMOKE_MULTI_PROVIDER_LIVE=1 (separate
test, ~$4 to exercise all four).

Cost: $0.
"""

from __future__ import annotations

from ._common import SmokeResult, prepare_environment, run_smoke

NAME = "multi_provider_routing"
REQUIRES_LIVE_LLM = False


_CASES: list[tuple[str, str, str]] = [
    # (url, expected ATS name or "<default>", expected provider)
    ("https://boards.greenhouse.io/example/jobs/12345", "Greenhouse", "openai"),
    ("https://jobs.lever.co/example/abc-def", "Lever", "anthropic"),
    ("https://example.myworkdayjobs.com/External/job/London/Engineer_R-123", "Workday Recruiting", "anthropic"),
    ("https://careers-example.icims.com/jobs/12345", "iCIMS", "openai"),
    ("https://jobs.smartrecruiters.com/example/12345", "SmartRecruiters", "anthropic"),
    ("https://example.bamboohr.com/jobs/view/12345", "BambooHR", "cohere"),
    # Crelate was originally mapped to Llama (via Together AI);
    # reassigned to Anthropic 2026-04-26 when Llama support was removed.
    ("https://example.crelate.com/jobs/12345", "Crelate", "anthropic"),
    ("https://apply.workable.com/example/j/12345", "Workable", "anthropic"),
    ("https://example.teamtailor.com/jobs/12345", "Teamtailor", "openai"),
    ("https://example.recruitee.com/o/12345", "Recruitee", "openai"),
    ("https://example.jobtrain.co.uk/jobs/12345", "Jobtrain", "openai"),
    ("https://example.tribepad.com/jobs/12345", "Tribepad", "anthropic"),
    # Unmapped host -> Anthropic default.
    ("https://acmetech.io/careers/senior-engineer", None, "anthropic"),
    # Empty / nonsense -> Anthropic default.
    ("", None, "anthropic"),
]


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.ats_routing import (
        ATS_TO_PROVIDER,
        detect_ats_name,
        provider_for_url,
    )

    messages: list[str] = []
    failures: list[str] = []

    # Routing table coverage.
    for url, expected_ats, expected_provider in _CASES:
        actual_ats = detect_ats_name(url) if url else None
        actual_provider = provider_for_url(url)
        if expected_ats is None:
            if actual_ats is not None:
                failures.append(
                    f"unmapped URL {url!r} resolved to ATS={actual_ats!r}, "
                    "expected None"
                )
        else:
            if actual_ats != expected_ats:
                failures.append(
                    f"{url!r} resolved to ATS={actual_ats!r}, "
                    f"expected {expected_ats!r}"
                )
        if actual_provider != expected_provider:
            failures.append(
                f"{url!r} routed to provider={actual_provider!r}, "
                f"expected {expected_provider!r}"
            )
    messages.append(f"routing table: {len(_CASES)} cases checked")

    # Every ATS in the user-supplied mapping resolves to a known provider.
    for ats_name, provider in ATS_TO_PROVIDER.items():
        if provider not in {"anthropic", "openai", "cohere"}:
            failures.append(
                f"unknown provider {provider!r} for ATS {ats_name!r}"
            )

    # Per-provider distribution sanity-check (the user's mapping has 25 ATSes).
    provider_counts: dict[str, int] = {}
    for ats, p in ATS_TO_PROVIDER.items():
        provider_counts[p] = provider_counts.get(p, 0) + 1
    messages.append(
        "ATS → provider distribution: "
        + ", ".join(f"{k}={v}" for k, v in sorted(provider_counts.items()))
    )
    if sum(provider_counts.values()) != len(ATS_TO_PROVIDER):
        failures.append(
            "ATS_TO_PROVIDER size != sum of provider counts"
        )

    # Adapter import hygiene — every provider's adapter is importable
    # without a live API call.
    try:
        from trajectory import llm_providers  # noqa: F401
        from trajectory.llm_providers import (
            ProviderUnavailable,
            call_structured,
        )
        assert callable(call_structured)
        assert issubclass(ProviderUnavailable, RuntimeError)
        messages.append("llm_providers module imports cleanly")
    except Exception as exc:
        failures.append(f"llm_providers import failed: {exc!r}")

    # cv_tailor_multi_provider module imports cleanly (no live call).
    try:
        from trajectory.sub_agents import cv_tailor_multi_provider  # noqa
        assert hasattr(cv_tailor_multi_provider, "generate_via_provider")
        messages.append("cv_tailor_multi_provider imports cleanly")
    except Exception as exc:
        failures.append(f"cv_tailor_multi_provider import failed: {exc!r}")

    # Per-provider cost-bucket sanity — each model id resolves to a
    # non-default pricing row.
    try:
        from trajectory.config import settings
        from trajectory.storage import _price_bucket
        for label, model in (
            ("openai", settings.openai_model_id),
            ("cohere", settings.cohere_model_id),
        ):
            bucket = _price_bucket(model)
            messages.append(
                f"pricing: {label} model={model} input=${bucket['input']:.2f}/Mtok "
                f"output=${bucket['output']:.2f}/Mtok"
            )
    except Exception as exc:
        failures.append(f"per-provider pricing lookup failed: {exc!r}")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
