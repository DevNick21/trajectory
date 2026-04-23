"""Tests for cv_latex_writer agent (Anthropic SDK fully mocked)."""

from __future__ import annotations

import json

import pytest

from trajectory.schemas import CVOutput, LatexCVOutput
from trajectory.sub_agents import cv_latex_writer


def _cv() -> CVOutput:
    return CVOutput(
        name="Jane R&D Engineer",  # contains '&' to test escape awareness
        contact={"email": "jane@x.com"},
        professional_summary="Built systems with 100% reliability targets.",
        experience=[],
        education=[],
        skills=["Python", "C++"],
    )


@pytest.mark.asyncio
async def test_writer_returns_latex_output(monkeypatch):
    """Writer wraps call_agent; assert it passes the right kwargs and
    returns the LatexCVOutput unchanged."""
    captured = {}

    async def fake_call_agent(**kwargs):
        captured.update(kwargs)
        # Return a hand-crafted LatexCVOutput as if the model emitted it.
        return LatexCVOutput(
            template="modern_one_column",
            tex_source=(
                "\\documentclass{article}\\begin{document}"
                "Jane R\\&D Engineer\\end{document}"
            ),
            packages_used=["geometry", "xcolor"],
            writer_notes="Single column, escaped & in name.",
        )

    monkeypatch.setattr(cv_latex_writer, "call_agent", fake_call_agent)

    template_refs = {
        "modern_one_column": "% modern reference\n\\documentclass{article}\n",
        "traditional_two_column": "% traditional reference\n\\documentclass{article}\n",
    }

    result = await cv_latex_writer.run(
        cv=_cv(),
        template="modern_one_column",
        template_refs=template_refs,
        session_id="s1",
    )

    assert isinstance(result, LatexCVOutput)
    assert "Jane R\\&D Engineer" in result.tex_source

    # Verify the writer passed both template references and the chosen
    # template down to the model.
    user_input = captured["user_input"]
    payload = json.loads(user_input)
    assert payload["template"] == "modern_one_column"
    assert "modern_one_column" in payload["template_references"]
    assert "traditional_two_column" in payload["template_references"]
    assert "% modern reference" in payload["template_references"]["modern_one_column"]
    assert captured["agent_name"] == "cv_latex_writer"


@pytest.mark.asyncio
async def test_writer_rejects_unknown_template(monkeypatch):
    async def fake_call_agent(**kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(cv_latex_writer, "call_agent", fake_call_agent)

    with pytest.raises(ValueError) as exc:
        await cv_latex_writer.run(
            cv=_cv(),
            template="not_a_real_template",
            template_refs={
                "modern_one_column": "x",
                "traditional_two_column": "y",
            },
        )
    assert "not in template_refs" in str(exc.value)
