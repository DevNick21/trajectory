"""Tests for the LaTeX renderer's compile + retry loop.

Subprocess + agent calls fully mocked. No pdflatex required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from trajectory.renderers import cv_latex
from trajectory.schemas import CVOutput, LatexCVOutput, LatexRepairOutput


def _cv() -> CVOutput:
    return CVOutput(
        name="Test User",
        contact={"email": "t@x.com"},
        professional_summary="Summary.",
        experience=[],
        education=[],
        skills=["Python"],
    )


_REAL_TEX = "\\documentclass{article}\\begin{document}Hello\\end{document}"


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# pdflatex missing → returns None immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_pdflatex_returns_none(out_dir, monkeypatch):
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: None)

    writer_called = AsyncMock()
    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_writer.run", writer_called,
    )

    result = await cv_latex.render_latex_pdf(
        _cv(), target_role=None, out_dir=out_dir,
    )
    assert result is None
    writer_called.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path: writer succeeds, compile succeeds first try
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_pdf(out_dir, monkeypatch):
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: "/usr/bin/pdflatex")

    pdf_path = out_dir / "cv_latex_sess1.pdf"

    def fake_compile(tex_source, out, *, filename_stem):
        # Simulate successful compile by writing a fake PDF.
        target = out / f"{filename_stem}.pdf"
        target.write_bytes(b"%PDF-1.4 fake")
        return target, ""

    monkeypatch.setattr(cv_latex, "_compile_tex", fake_compile)

    fake_writer_output = LatexCVOutput(
        template="modern_one_column",
        tex_source=_REAL_TEX,
        packages_used=["geometry"],
        writer_notes="ok",
    )

    async def fake_writer_run(**kwargs):
        return fake_writer_output

    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_writer.run", fake_writer_run,
    )

    result = await cv_latex.render_latex_pdf(
        _cv(), target_role="Senior Engineer",
        session_id="sess1", out_dir=out_dir,
    )
    assert result == pdf_path
    assert pdf_path.exists()


# ---------------------------------------------------------------------------
# Compile fails once, repair succeeds → returns PDF on second attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_on_second_attempt(out_dir, monkeypatch):
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: "/usr/bin/pdflatex")

    attempts = {"count": 0}

    def fake_compile(tex_source, out, *, filename_stem):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return None, "! Undefined control sequence \\foo"
        target = out / f"{filename_stem}.pdf"
        target.write_bytes(b"%PDF-1.4 repaired")
        return target, ""

    monkeypatch.setattr(cv_latex, "_compile_tex", fake_compile)

    async def fake_writer_run(**kwargs):
        return LatexCVOutput(
            template="modern_one_column",
            tex_source="bad tex",
            packages_used=[],
            writer_notes="x",
        )

    async def fake_repairer_run(**kwargs):
        return LatexRepairOutput(
            tex_source=_REAL_TEX,
            change_summary="Removed \\foo command.",
        )

    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_writer.run", fake_writer_run,
    )
    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_repairer.run", fake_repairer_run,
    )

    result = await cv_latex.render_latex_pdf(
        _cv(), session_id="sess2", out_dir=out_dir,
    )
    assert result is not None
    assert result.read_bytes() == b"%PDF-1.4 repaired"
    assert attempts["count"] == 2


# ---------------------------------------------------------------------------
# Compile fails twice → returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_failures_returns_none(out_dir, monkeypatch):
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: "/usr/bin/pdflatex")

    def fake_compile(tex_source, out, *, filename_stem):
        return None, "still failing"

    monkeypatch.setattr(cv_latex, "_compile_tex", fake_compile)

    async def fake_writer_run(**kwargs):
        return LatexCVOutput(
            template="modern_one_column",
            tex_source="x",
            packages_used=[],
            writer_notes="x",
        )

    async def fake_repairer_run(**kwargs):
        return LatexRepairOutput(
            tex_source="another bad attempt",
            change_summary="tried to escape & on line 12",
        )

    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_writer.run", fake_writer_run,
    )
    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_repairer.run", fake_repairer_run,
    )

    result = await cv_latex.render_latex_pdf(
        _cv(), session_id="sess3", out_dir=out_dir, max_retries=2,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Repairer gives up (empty tex_source / unfixable:) → returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repairer_gives_up_returns_none(out_dir, monkeypatch):
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: "/usr/bin/pdflatex")

    compile_calls = {"n": 0}

    def fake_compile(tex_source, out, *, filename_stem):
        compile_calls["n"] += 1
        return None, "missing package minted"

    monkeypatch.setattr(cv_latex, "_compile_tex", fake_compile)

    async def fake_writer_run(**kwargs):
        return LatexCVOutput(
            template="modern_one_column",
            tex_source="x",
            packages_used=[],
            writer_notes="x",
        )

    async def fake_repairer_run(**kwargs):
        return LatexRepairOutput(
            tex_source="",
            change_summary="unfixable: requires non-allow-list package minted",
        )

    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_writer.run", fake_writer_run,
    )
    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_repairer.run", fake_repairer_run,
    )

    result = await cv_latex.render_latex_pdf(
        _cv(), session_id="sess4", out_dir=out_dir,
    )
    assert result is None
    # The repairer's "unfixable" verdict should short-circuit further
    # compile attempts beyond the first.
    assert compile_calls["n"] == 1


# ---------------------------------------------------------------------------
# Writer raises → renderer logs + returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_exception_returns_none(out_dir, monkeypatch):
    monkeypatch.setattr(cv_latex.shutil, "which", lambda name: "/usr/bin/pdflatex")

    async def boom(**kwargs):
        raise RuntimeError("api blew up")

    monkeypatch.setattr(
        "trajectory.sub_agents.cv_latex_writer.run", boom,
    )

    result = await cv_latex.render_latex_pdf(
        _cv(), session_id="sess5", out_dir=out_dir,
    )
    assert result is None
