"""Career narrator — Haiku-cheap CV-to-bio summariser.

Step 8 of the onboarding wizard ("Career so far") used to pre-fill
with the raw CV bullets, which is exactly what we already have on
file in the role list. This agent does the reshape the user actually
asked for: a chronological narrative in third person, 2-3 paragraphs,
that summarises career arc + key inflection points.

Feeds the retrievable career store. The CV-tailor + cover-letter
generators retrieve against this when drafting; a coherent narrative
gives them a much better anchor than 30 separate bullet rows.

Routing: Haiku via `call_structured`. Cheap (~$0.0005) and fast (~2s).
Pure reshape — no judgement needed. Per CLAUDE.md Rule 7.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..config import settings
from ..llm import call_structured
from ..schemas import CVImport, CVImportRole

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are AskPicky's career narrator. Given a
parsed CV — name, professional summary, role rows in
reverse-chronological order, education, and projects — produce a
short, chronological narrative bio in the user's own voice (third
person is fine; first person is fine too if their summary uses it).

Constraints:
1. 2-3 paragraphs. 100-200 words total.
2. Chronological: start with education / first role, end with the
   most recent role. The CV is given to you reverse-chron; you
   reverse it back.
3. Each role gets one sentence describing what they did + scope.
   Don't list every bullet — pick the most defining one.
4. Honest. If a role is a 2-month contract, say so. Don't inflate.
5. No clichés (no "passionate", "results-driven", "proven track
   record", "leverage" as a verb). The self-audit runs over this
   downstream and will flag them.
6. Pick up signal from the professional_summary if present — it's
   the user's own framing of what they do.
7. Output the narrative as a single field. No headers, no bullets,
   no markdown.

Example shape (not content):
   "Kene started in computer engineering at <uni>, interned at <X>
    on <Y>, then joined <Z> where they <achievement>. Most recently
    they've been at <current>, focusing on <area>. Their throughline
    is <observed theme>."
"""


class CareerNarrative(BaseModel):
    narrative: str = Field(
        description="2-3 paragraph chronological career bio, 100-200 words.",
        min_length=80,
        max_length=2000,
    )


def _format_cv_for_narrator(cv: CVImport) -> str:
    """Tight digest of the CV for Haiku. Skips raw_text — already long."""
    lines: list[str] = []
    if cv.name:
        lines.append(f"Name: {cv.name}")
    if cv.base_location:
        lines.append(f"Location: {cv.base_location}")
    if cv.professional_summary:
        lines.append(f"Their own summary: {cv.professional_summary}")
    if cv.education:
        lines.append("\nEducation:")
        for ed in cv.education:
            qual = getattr(ed, "qualification", None) or ""
            inst = getattr(ed, "institution", None) or ""
            dates = getattr(ed, "dates", None) or ""
            lines.append(f"  - {qual} at {inst} ({dates})".strip())
    if cv.roles:
        lines.append("\nRoles (reverse-chronological — narrator should flip to chronological):")
        for role in cv.roles:
            head = f"  - {role.title} at {role.company}"
            if role.dates:
                head += f" ({role.dates})"
            lines.append(head)
            for b in (role.bullets or [])[:3]:
                lines.append(f"      • {b}")
    if cv.projects:
        lines.append("\nProjects:")
        for p in cv.projects:
            name = getattr(p, "name", None) or ""
            desc = getattr(p, "description", None) or ""
            lines.append(f"  - {name}: {desc[:150]}")
    return "\n".join(lines)


async def narrate(
    *,
    cv: CVImport,
    session_id: Optional[str] = None,
) -> str:
    """Return a Picky-voice narrative bio derived from a parsed CV."""
    digest = _format_cv_for_narrator(cv)
    if not digest.strip():
        return ""
    out: CareerNarrative = await call_structured(
        agent_name="career_narrator",
        system_prompt=_SYSTEM_PROMPT,
        user_input=digest,
        output_schema=CareerNarrative,
        model=settings.haiku_model_id,
        effort="medium",
        session_id=session_id,
    )
    logger.info(
        "career_narrator: produced %d-char narrative for cv with %d role(s)",
        len(out.narrative), len(cv.roles),
    )
    return out.narrative
