"""cv_latex_writer — translates a CVOutput into a compilable .tex file.

Sonnet 4.6 medium effort. LaTeX generation is context-sensitive
schema-translation with escape-rule awareness — not pure extraction,
not deep reasoning. PROCESS.md Entry 37.

Registered in `HIGH_STAKES_AGENTS` because the output is fed directly
to a subprocess (pdflatex); any injection that landed in the CVOutput
must be contained before reaching the shell.
"""

from __future__ import annotations

import json
from typing import Optional

from ..config import settings
from ..llm import call_agent
from ..prompts import load_prompt
from ..schemas import CVOutput, LatexCVOutput

SYSTEM_PROMPT = load_prompt("cv_latex_writer")


async def run(
    *,
    cv: CVOutput,
    template: str,
    template_refs: dict[str, str],
    session_id: Optional[str] = None,
) -> LatexCVOutput:
    """Generate a .tex document for the given CV and template style.

    `template_refs` is a dict mapping template name → reference .tex
    source, passed verbatim so the writer agent sees the concrete
    style guide.
    """
    if template not in template_refs:
        raise ValueError(
            f"template {template!r} not in template_refs "
            f"({sorted(template_refs)})"
        )

    user_input = json.dumps(
        {
            "template": template,
            "cv_output": cv.model_dump(mode="json"),
            "template_references": template_refs,
            "instructions": (
                "Produce a LatexCVOutput whose `tex_source` compiles with "
                "pdflatex using only the allow-list packages. Follow the "
                "style of the matching reference in template_references."
            ),
        },
        default=str,
    )

    return await call_agent(
        agent_name="cv_latex_writer",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=LatexCVOutput,
        model=settings.sonnet_model_id,
        effort="medium",
        session_id=session_id,
        max_retries=1,
    )
