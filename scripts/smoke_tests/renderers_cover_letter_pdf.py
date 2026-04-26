"""Smoke test — Cover letter .pdf renderer (no LLM).

Cost: $0.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ._common import (
    SmokeResult,
    build_synthetic_cover_letter_output,
    prepare_environment,
    run_smoke,
)

NAME = "renderers_cover_letter_pdf"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.renderers import render_cover_letter_pdf

    messages: list[str] = []
    failures: list[str] = []

    cl = build_synthetic_cover_letter_output()
    out_dir = Path(tempfile.mkdtemp(prefix="smoke-clpdf-"))
    path = render_cover_letter_pdf(cl, out_dir, sender_name="Smoke Test")

    if not path.exists():
        failures.append(f"render_cover_letter_pdf returned {path} but file missing.")
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
