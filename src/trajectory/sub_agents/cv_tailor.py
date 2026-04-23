"""Phase 4 — CV Tailor dispatcher.

Selects between:
  - `cv_tailor_legacy.generate` — original single-call path. Production
    default.
  - `cv_tailor_agentic.generate` — multi-turn FAISS retrieval path.
    Opt-in via `settings.enable_agentic_cv_tailor`.

Signature matches both backends so call sites (orchestrator) don't
change. Agentic path catches its own errors here and falls back to
legacy — a runtime failure in the agentic path must not degrade the
user-visible CV.

PROCESS.md Entry 36.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import settings
from ..llm import AgentCallFailed
from ..schemas import (
    CareerEntry,
    CVOutput,
    ExtractedJobDescription,
    ResearchBundle,
    STARPolish,
    UserProfile,
    WritingStyleProfile,
)
from ..validators.citations import ValidationContext
from . import cv_tailor_agentic, cv_tailor_legacy

logger = logging.getLogger(__name__)


async def generate(
    jd: ExtractedJobDescription,
    research_bundle: ResearchBundle,
    user: UserProfile,
    retrieved_entries: list[CareerEntry],
    style_profile: WritingStyleProfile,
    star_material: Optional[list[STARPolish]] = None,
    citation_ctx: Optional[ValidationContext] = None,
) -> CVOutput:
    """Dispatch CV generation. Flag off → legacy. Flag on → agentic with
    legacy fallback on failure."""
    if settings.enable_agentic_cv_tailor:
        try:
            return await cv_tailor_agentic.generate(
                jd=jd,
                research_bundle=research_bundle,
                user=user,
                retrieved_entries=retrieved_entries,
                style_profile=style_profile,
                star_material=star_material,
                citation_ctx=citation_ctx,
            )
        except AgentCallFailed as exc:
            logger.warning(
                "Agentic CV tailor failed; falling back to legacy: %s", exc,
            )
        except Exception as exc:
            # Pydantic ValidationError, network hiccup, whatever — the
            # legacy path is the known-good production surface, so fall
            # back rather than propagate.
            logger.warning(
                "Agentic CV tailor raised %s; falling back to legacy: %r",
                type(exc).__name__, exc,
            )

    return await cv_tailor_legacy.generate(
        jd=jd,
        research_bundle=research_bundle,
        user=user,
        retrieved_entries=retrieved_entries,
        style_profile=style_profile,
        star_material=star_material,
        citation_ctx=citation_ctx,
    )
