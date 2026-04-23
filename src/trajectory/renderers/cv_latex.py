"""LaTeX CV renderer — third PDF path alongside cv_docx and cv_pdf.

Strictly additive (PROCESS.md Entry 37): if pdflatex is missing, the
writer agent fails, or the repair loop exhausts, this renderer
returns None and the caller's existing docx + reportlab-PDF outputs
ship unchanged. The user never sees a LaTeX-related error.

Flow:
  1. `which pdflatex` — bail out cleanly if absent.
  2. `_choose_template` — keyword heuristic on target_role.
  3. `cv_latex_writer.run(...)` → LatexCVOutput.
  4. `_compile_tex(...)` — pdflatex in a tempdir; returns
     `(pdf_path, error_log)`.
  5. On failure, `cv_latex_repairer.run(...)` → patched .tex; loop
     up to `max_retries=2`. Repairer may give up by returning empty
     `tex_source` with a `change_summary` starting `"unfixable: "`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..schemas import CVOutput

logger = logging.getLogger(__name__)


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_TEMPLATE_FILES = {
    "modern_one_column": "modern_one_column.tex.jinja",
    "traditional_two_column": "traditional_two_column.tex.jinja",
}

_TRADITIONAL_KEYWORDS = (
    "analyst", "associate", "consultant", "banking", "investment",
    "compliance", "audit", "actuar", "finance", "insurance",
    "regulatory", "legal",
)

_COMPILE_TIMEOUT_S = 30


def _choose_latex_template(cv: CVOutput, target_role: Optional[str]) -> str:
    """Heuristic selection between the two templates.

    Documented heuristic (PROCESS.md Entry 37) — finance / consulting /
    regulated keywords pick the traditional two-column layout;
    everything else (including unknown / empty target_role) gets the
    modern single-column template.
    """
    if not target_role:
        return "modern_one_column"
    role_lower = target_role.lower()
    if any(kw in role_lower for kw in _TRADITIONAL_KEYWORDS):
        return "traditional_two_column"
    return "modern_one_column"


def _load_template_refs() -> dict[str, str]:
    """Load both reference .tex files into memory."""
    refs: dict[str, str] = {}
    for name, filename in _TEMPLATE_FILES.items():
        path = _TEMPLATES_DIR / filename
        if not path.exists():
            logger.warning("LaTeX template missing: %s", path)
            continue
        refs[name] = path.read_text(encoding="utf-8")
    return refs


def _compile_tex(
    tex_source: str,
    out_dir: Path,
    *,
    filename_stem: str,
) -> tuple[Optional[Path], str]:
    """Compile .tex to .pdf in a tempdir; copy result to out_dir on
    success.

    Returns (pdf_path, "") on success or (None, last 50 lines of .log)
    on any failure. Cleans up the tempdir always.
    """
    if shutil.which("pdflatex") is None:
        return None, "pdflatex binary not found on PATH"

    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cv_latex_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        tex_path = tmpdir / f"{filename_stem}.tex"
        tex_path.write_text(tex_source, encoding="utf-8")

        try:
            result = subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={tmpdir}",
                    str(tex_path),
                ],
                capture_output=True,
                text=True,
                timeout=_COMPILE_TIMEOUT_S,
                cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            return None, f"pdflatex timed out after {_COMPILE_TIMEOUT_S}s"
        except OSError as exc:
            return None, f"pdflatex invocation failed: {exc!r}"

        pdf_path = tmpdir / f"{filename_stem}.pdf"
        if result.returncode == 0 and pdf_path.exists():
            dest = out_dir / f"{filename_stem}.pdf"
            shutil.copyfile(pdf_path, dest)
            return dest, ""

        log_path = tmpdir / f"{filename_stem}.log"
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            tail = "\n".join(log_text.splitlines()[-50:])
        else:
            tail = (result.stderr or result.stdout or "")[-2000:]
        return None, tail


async def render_latex_pdf(
    cv: CVOutput,
    *,
    target_role: Optional[str] = None,
    session_id: Optional[str] = None,
    out_dir: Path,
    max_retries: int = 2,
) -> Optional[Path]:
    """Render a CV to PDF via LaTeX + pdflatex.

    Returns the PDF path on success; None on any failure (pdflatex
    missing, agent error, compile error after retries, repairer gave
    up). Failures are logged at WARNING and never raised — additive
    contract.
    """
    if shutil.which("pdflatex") is None:
        logger.warning("pdflatex not installed; skipping LaTeX CV render")
        return None

    template = _choose_latex_template(cv, target_role)
    template_refs = _load_template_refs()
    if template not in template_refs:
        logger.warning(
            "LaTeX template ref %r missing on disk; skipping", template,
        )
        return None

    # Lazy imports — agent modules pull pydantic + httpx; we don't want
    # to pay that import cost when pdflatex is absent.
    from ..sub_agents import cv_latex_repairer, cv_latex_writer

    try:
        latex_output = await cv_latex_writer.run(
            cv=cv,
            template=template,
            template_refs=template_refs,
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning("cv_latex_writer failed: %r", exc)
        return None

    tex_source = latex_output.tex_source
    if not tex_source:
        logger.warning("cv_latex_writer returned empty tex_source")
        return None

    filename_stem = f"cv_latex_{session_id or 'nosession'}"

    for attempt in range(max_retries + 1):
        pdf_path, error_log = await asyncio.to_thread(
            _compile_tex, tex_source, out_dir, filename_stem=filename_stem,
        )
        if pdf_path is not None:
            logger.info("LaTeX CV compiled on attempt %d", attempt + 1)
            return pdf_path

        if attempt >= max_retries:
            logger.warning(
                "LaTeX CV compile failed after %d retries; last error: %s",
                max_retries, error_log[:400],
            )
            return None

        try:
            repair_output = await cv_latex_repairer.run(
                failing_tex=tex_source,
                error_log=error_log,
                template=template,
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning("cv_latex_repairer failed: %r", exc)
            return None

        summary = repair_output.change_summary or ""
        if not repair_output.tex_source or summary.startswith("unfixable:"):
            logger.warning(
                "cv_latex_repairer gave up: %s", summary or "empty tex",
            )
            return None
        tex_source = repair_output.tex_source

    return None
