"""Smoke test — CV tailor + renderers.

Exercises the draft_cv orchestrator end-to-end:
  - _shield_bundle over the fixture (Tier 1 redactions and Tier 2 routing)
  - build_context (citation validation context)
  - cv_tailor.generate (Opus xhigh + extended thinking)
  - self_audit + _apply_rewrites_to_strings patch loop
  - render_cv_docx + render_cv_pdf produce files on disk

Cost: ~$1.00-$2.00 (Opus xhigh generator + self-audit).
"""

from __future__ import annotations

from pathlib import Path

from ._common import (
    SmokeResult,
    build_test_session,
    build_test_user,
    load_fixture_bundle,
    prepare_environment,
    require_anthropic_key,
    run_smoke,
)

NAME = "phase4_cv"
REQUIRES_LIVE_LLM = True
ESTIMATED_COST_USD = 1.50


async def _body() -> tuple[list[str], list[str], float]:
    tmp = prepare_environment()
    missing = require_anthropic_key()
    if missing:
        return [], [missing], 0.0

    from trajectory.config import settings
    # Keep rendered files inside the smoke tempdir.
    settings.generated_dir = tmp / "generated"
    settings.generated_dir.mkdir(parents=True, exist_ok=True)

    from trajectory.orchestrator import handle_draft_cv
    from trajectory.storage import Storage

    bundle = load_fixture_bundle()
    user = build_test_user("uk_resident")
    session = build_test_session(user.user_id, intent="draft_cv")

    storage = Storage()
    await storage.initialise()
    await storage.save_user_profile(user)
    await storage.save_session(session)
    await storage.save_phase1_output(session.session_id, bundle)
    session = await storage.get_session(session.session_id)  # reload with phase1

    messages: list[str] = []
    failures: list[str] = []

    try:
        # handle_draft_cv returns (cv, docx, pdf, latex_pdf?) since the
        # LaTeX renderer landed (PROCESS Entry 37). The 4th element is
        # None when pdflatex is missing or the LaTeX path failed.
        cv, docx_path, pdf_path, latex_pdf_path = await handle_draft_cv(
            session=session,
            user=user,
            storage=storage,
        )
    except Exception as exc:
        failures.append(f"handle_draft_cv raised: {exc!r}")
        return messages, failures, ESTIMATED_COST_USD

    messages.append(
        f"CVOutput: roles={len(cv.roles) if hasattr(cv, 'roles') else '?'}, "
        f"bullet_count="
        f"{sum(len(r.bullets) for r in getattr(cv, 'roles', []) or [])}"
    )
    messages.append(f"docx → {docx_path} ({_size(docx_path)} bytes)")
    messages.append(f"pdf  → {pdf_path} ({_size(pdf_path)} bytes)")
    if latex_pdf_path is not None:
        messages.append(
            f"latex pdf → {latex_pdf_path} ({_size(latex_pdf_path)} bytes)"
        )
    else:
        messages.append("latex pdf → skipped (pdflatex absent or render failed)")

    if not docx_path.exists() or docx_path.stat().st_size < 1_000:
        failures.append(f"DOCX renderer produced a tiny/missing file: {docx_path}")
    if not pdf_path.exists() or pdf_path.stat().st_size < 1_000:
        failures.append(f"PDF renderer produced a tiny/missing file: {pdf_path}")

    await storage.close()
    return messages, failures, ESTIMATED_COST_USD


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


async def run() -> SmokeResult:
    return await run_smoke(NAME, _body)


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run())
    print(result.summary())
    for m in result.messages:
        print("  ", m)
    for f in result.failures:
        print("  FAIL:", f)
