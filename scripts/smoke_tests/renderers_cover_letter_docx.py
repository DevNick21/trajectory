"""Smoke test — Cover letter .docx renderer (no LLM).

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

NAME = "renderers_cover_letter_docx"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.renderers import render_cover_letter_docx

    messages: list[str] = []
    failures: list[str] = []

    cl = build_synthetic_cover_letter_output()
    out_dir = Path(tempfile.mkdtemp(prefix="smoke-cldocx-"))
    path = render_cover_letter_docx(cl, out_dir, sender_name="Smoke Test")

    if not path.exists():
        failures.append(f"render_cover_letter_docx returned {path} but file missing.")
        return messages, failures, 0.0

    head = path.read_bytes()[:4]
    if head != b"PK\x03\x04":
        failures.append(f".docx magic bytes wrong: {head!r}")
    size = path.stat().st_size
    if size < 1_500:
        failures.append(f".docx suspiciously small: {size} bytes")
    messages.append(f"rendered {path.name} ({size} bytes)")

    from docx import Document
    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    if len(paragraphs) < 3:
        failures.append(f"rendered cover letter has only {len(paragraphs)} paragraphs")
    if "Yours sincerely" not in "\n".join(paragraphs):
        failures.append("signoff 'Yours sincerely' missing from rendered doc")
    messages.append(f"structural: {len(paragraphs)} non-empty paragraphs")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
