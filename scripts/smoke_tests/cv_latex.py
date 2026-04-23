"""Smoke test — LaTeX CV renderer (real pdflatex + real writer agent).

Gated behind `SMOKE_LATEX=1`. Cost ~$0.04 (Sonnet mid writer, maybe
one repair). Needs pdflatex on PATH; skips cleanly if absent.

Builds a minimal synthetic CVOutput, hands it to `render_latex_pdf`,
asserts the returned PDF exists and is non-trivially sized.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from ._common import (
    SmokeResult,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "cv_latex"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 0.04
_GATE_ENV = "SMOKE_LATEX"


async def _body() -> tuple[list[str], list[str], float]:
    messages: list[str] = []
    failures: list[str] = []

    if os.environ.get(_GATE_ENV, "") != "1":
        messages.append(
            f"skipped — set {_GATE_ENV}=1 to opt into the paid LaTeX "
            "render (~$0.04)"
        )
        return messages, failures, 0.0

    if shutil.which("pdflatex") is None:
        messages.append("pdflatex not on PATH; skipping live render")
        return messages, failures, 0.0

    tmp = prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.renderers.cv_latex import render_latex_pdf
    from trajectory.schemas import (
        CVBullet,
        Citation,
        CVOutput,
        CVRole,
    )

    cv = CVOutput(
        name="Smoke Test Candidate",
        contact={
            "email": "smoke@example.com",
            "phone": "+44 7700 900000",
            "linkedin": "https://linkedin.com/in/smoke",
        },
        professional_summary=(
            "Senior engineer shipping Python systems at scale, focused on "
            "observability-first design and cost-efficient infrastructure."
        ),
        experience=[
            CVRole(
                title="Senior Engineer",
                company="Acme Ltd",
                dates="2023 -- Present",
                bullets=[
                    CVBullet(
                        text=(
                            "[ce:e1] Reduced p99 latency by 40% via query "
                            "plan refactor. Used Python 3.12 & asyncio."
                        ),
                        citations=[Citation(kind="career_entry", entry_id="e1")],
                    ),
                    CVBullet(
                        text=(
                            "[ce:e2] Shipped R&D prototype — cost savings "
                            "of £100k annually."
                        ),
                        citations=[Citation(kind="career_entry", entry_id="e2")],
                    ),
                ],
            ),
        ],
        education=[{"degree": "BSc Computer Science", "year": "2018"}],
        skills=["Python", "AWS", "Kubernetes", "observability"],
    )

    out_dir = Path(tmp) / "cv_latex_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = await render_latex_pdf(
        cv,
        target_role="Senior Platform Engineer",
        session_id="smoke_latex",
        out_dir=out_dir,
    )

    if result is None:
        failures.append(
            "render_latex_pdf returned None — writer or compile failed"
        )
        return messages, failures, ESTIMATED_COST_USD

    if not result.exists():
        failures.append(f"returned path does not exist: {result}")
        return messages, failures, ESTIMATED_COST_USD

    size = result.stat().st_size
    messages.append(f"PDF written: {result.name}, {size} bytes")
    if size < 10_000:
        failures.append(f"PDF suspiciously small: {size} bytes")

    with result.open("rb") as f:
        header = f.read(4)
    if header != b"%PDF":
        failures.append(f"not a PDF (magic bytes: {header!r})")

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
