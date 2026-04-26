"""Smoke test — CV .pdf renderer (no LLM).

Builds a synthetic CVOutput, renders via reportlab, validates %PDF-
magic bytes + file size.

Cost: $0.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ._common import (
    SmokeResult,
    build_synthetic_cv_output,
    prepare_environment,
    run_smoke,
)

NAME = "renderers_cv_pdf"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.renderers import render_cv_pdf

    messages: list[str] = []
    failures: list[str] = []

    cv = build_synthetic_cv_output()
    out_dir = Path(tempfile.mkdtemp(prefix="smoke-cvpdf-"))
    path = render_cv_pdf(cv, out_dir, company="Acme")

    if not path.exists():
        failures.append(f"render_cv_pdf returned {path} but file does not exist.")
        return messages, failures, 0.0

    head = path.read_bytes()[:5]
    if head != b"%PDF-":
        failures.append(f"PDF magic bytes wrong: {head!r}")
    size = path.stat().st_size
    if size < 500:
        failures.append(f"PDF suspiciously small: {size} bytes")
    messages.append(f"rendered {path.name} ({size} bytes)")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
