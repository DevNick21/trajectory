"""Smoke test — onboarding CV parser (PROCESS Entry 49).

Sonnet pass: free-form CV text -> CVImport. Costs ~$0.05 live.
Set SMOKE_CV_PARSER_MOCK=1 to skip the LLM and assert the
file-format dispatcher only.

Asserts (live):
  - parse() returns a CVImport with raw_text populated
  - >=2 roles extracted from a 4-role fixture
  - >=3 skills extracted
  - confidence >= 5
  - raw_text is the (un-shielded) original

Asserts (always):
  - extract_text() round-trips a plain-text upload
"""

from __future__ import annotations

import asyncio
import os

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "cv_parser"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.05


_FIXTURE_CV = """
Jane Example
London · jane@example.com · +44 7700 900000

PROFILE
Senior software engineer, six years building payment infrastructure at
mid-stage UK fintechs. Strong on Python services, observability, and
reducing on-call pain.

EXPERIENCE

Senior Software Engineer — Capital on Tap
Jan 2023 – Present, London
* Designed and shipped the merchant rewards ledger; cut reconciliation
  errors by 70 percent.
* Mentored two junior engineers through their probation period.
* Reduced p99 transaction latency from 480ms to 210ms by re-sharding
  the postgres write path.

Software Engineer — Monzo Bank
Sep 2020 – Dec 2022, London
* Owned the payments-rails ingestion service handling 30M events/day.
* Wrote the team's runbook for debugging stuck SEPA payments.
* Improved CI from 22 minutes to 7 minutes by parallelising the
  integration suite.

Junior Engineer — Acme Tech Ltd
Jul 2018 – Aug 2020, Manchester
* Built the internal analytics dashboard from scratch.
* Migrated the company off Heroku to AWS Fargate.

EDUCATION
University of Manchester — BSc Computer Science (2015 – 2018)

PROJECTS
ledger-bench (open source) — A small benchmarking harness for
double-entry ledger implementations. Used by two other UK fintechs.

SKILLS
Python, Go, PostgreSQL, Kubernetes, AWS, Datadog, Pagerduty, Terraform,
GitHub Actions, gRPC, REST, Kafka
"""


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    messages: list[str] = []
    failures: list[str] = []

    # File-format dispatcher (always runs — no LLM cost).
    from trajectory.sub_agents.cv_parser import extract_text

    plain = "Hello\nWorld\n"
    out = extract_text(data=plain.encode("utf-8"), filename="resume.txt")
    if out.strip() != plain.strip():
        failures.append(f"extract_text(.txt) round-trip mismatch: {out!r}")
    else:
        messages.append("extract_text(.txt) round-trip OK")

    mock = os.getenv("SMOKE_CV_PARSER_MOCK", "").lower() in {"1", "true", "yes"}
    if mock:
        messages.append("MOCK: skipping live Sonnet pass.")
        return messages, failures, 0.0

    missing = require_anthropic_key()
    if missing:
        return messages, [missing], 0.0

    from trajectory.sub_agents.cv_parser import parse as parse_cv

    try:
        imp = await parse_cv(cv_text=_FIXTURE_CV)
    except Exception as exc:
        failures.append(f"parse() raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"name={imp.name!r} location={imp.base_location!r} "
        f"roles={len(imp.roles)} edu={len(imp.education)} "
        f"projects={len(imp.projects)} skills={len(imp.skills)} "
        f"confidence={imp.extraction_confidence}"
    )

    if not imp.raw_text or imp.raw_text != _FIXTURE_CV:
        failures.append(
            "raw_text not preserved verbatim from caller input — "
            "style_extractor downstream needs the original text."
        )
    if len(imp.roles) < 2:
        failures.append(f"only {len(imp.roles)} roles extracted; expected >=2")
    if len(imp.skills) < 3:
        failures.append(f"only {len(imp.skills)} skills extracted; expected >=3")
    if imp.extraction_confidence < 5:
        failures.append(
            f"confidence {imp.extraction_confidence} < 5 on a clean fixture; "
            "Sonnet flagged its own extraction as low quality."
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
