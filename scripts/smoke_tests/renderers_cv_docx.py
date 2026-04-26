"""Smoke test — CV .docx renderer (no LLM).

Builds a synthetic CVOutput, renders via python-docx, then validates
magic bytes + file size. Catches python-docx API drift without an Opus
round-trip.

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

NAME = "renderers_cv_docx"
REQUIRES_LIVE_LLM = False


async def _body() -> tuple[list[str], list[str], float]:
    prepare_environment()

    from trajectory.renderers import render_cv_docx

    messages: list[str] = []
    failures: list[str] = []

    cv = build_synthetic_cv_output()
    out_dir = Path(tempfile.mkdtemp(prefix="smoke-cvdocx-"))
    path = render_cv_docx(cv, out_dir, company="Acme")

    if not path.exists():
        failures.append(f"render_cv_docx returned {path} but file does not exist.")
        return messages, failures, 0.0

    head = path.read_bytes()[:4]
    if head != b"PK\x03\x04":
        failures.append(f".docx magic bytes wrong: {head!r}")
    size = path.stat().st_size
    if size < 2_000:
        failures.append(f".docx suspiciously small: {size} bytes")
    messages.append(f"rendered {path.name} ({size} bytes)")

    # Structural: open and walk paragraphs to verify non-empty.
    from docx import Document
    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    if len(paragraphs) < 5:
        failures.append(f"rendered doc has only {len(paragraphs)} non-empty paragraphs")
    if cv.name not in "\n".join(paragraphs):
        failures.append("candidate name missing from rendered doc")
    messages.append(f"structural: {len(paragraphs)} non-empty paragraphs")

    return messages, failures, 0.0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
