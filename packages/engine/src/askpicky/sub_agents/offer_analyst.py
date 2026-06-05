"""Offer letter analyst.

Pipeline:
  1. PDF text extracted locally via pypdf (no remote Files API).
  2. Analysis via call_agent with structured output.
  3. Market comparison via inline gov_data documents.
  4. Banned-phrase post-validation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..citation_docs import build_document_context
from ..config import settings
from ..llm import AgentCallFailed, call_agent
from ..schemas import (
    Citation,
    OfferAnalysis,
    OfferComponent,
    ResearchBundle,
    UserProfile,
)
from ..validators.banned_phrases import contains_banned

from pydantic import BaseModel

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are the AskPicky offer-letter analyst. Analyse the offer letter
text supplied in the prompt and answer for the user whose UK
profile is also supplied.

Return the analysis as ONE JSON object inside a code block. Do
NOT wrap in Markdown fences. Schema:

{
  "company_name": str,
  "role_title": str | null,
  "base_salary_gbp": {"label": str, "value_text": str} | null,
  "bonus": {"label": str, "value_text": str} | null,
  "equity": {"label": str, "value_text": str} | null,
  "benefits": [{"label": str, "value_text": str}, ...],
  "notice_period": {"label": str, "value_text": str} | null,
  "non_compete": {"label": str, "value_text": str} | null,
  "ip_assignment": {"label": str, "value_text": str} | null,
  "unusual_clauses": [{"label": str, "value_text": str}, ...],
  "market_comparison_note": str | null,
  "flags": [str, ...]
}

WHAT TO FLAG:
- base salary below ASHE p25 for the role's region
- base salary below the user's stated salary_floor
- non-compete duration > 6 months in the UK
- IP assignment that includes personal projects
- equity vesting cliff > 12 months
- notice period asymmetry (e.g. 1mo from employer, 3mo from employee)

Banned phrases apply. Be direct: "below market by 15%", not "could
be considered slightly below market in some interpretations".
"""


class _OfferAnalysisBody(BaseModel):
    company_name: str
    role_title: Optional[str] = None
    base_salary_gbp: Optional[dict] = None
    bonus: Optional[dict] = None
    equity: Optional[dict] = None
    benefits: list[dict] = []
    notice_period: Optional[dict] = None
    non_compete: Optional[dict] = None
    ip_assignment: Optional[dict] = None
    unusual_clauses: list[dict] = []
    market_comparison_note: Optional[str] = None
    flags: list[str] = []


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract raw text from a PDF using pypdf (local, no API call)."""
    try:
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except Exception as exc:
        logger.warning("offer_analyst: pypdf extraction failed: %s", exc)
        return "[PDF text extraction failed — raw bytes not readable as PDF]"


async def analyse(
    *,
    user: UserProfile,
    research_bundle: Optional[ResearchBundle] = None,
    file_id: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    text_pasted: Optional[str] = None,
    session_id: Optional[str] = None,
) -> OfferAnalysis:
    if not any([pdf_bytes, text_pasted]):
        raise ValueError(
            "analyse requires one of pdf_bytes or text_pasted."
        )

    # Extract offer text
    if pdf_bytes:
        offer_text = extract_pdf_text(pdf_bytes)
    else:
        offer_text = text_pasted or ""

    # Build inline context from research bundle
    context_text = ""
    if research_bundle is not None:
        context_text, _citation_map = build_document_context(
            bundle=research_bundle,
            career_entries=None,
            include_career_entries=False,
        )

    user_input = json.dumps({
        "user": {
            "name": user.name,
            "user_type": user.user_type,
            "base_location": user.base_location,
            "salary_floor": user.salary_floor,
            "salary_target": user.salary_target,
            "visa_route": (
                user.visa_status.route if user.visa_status else None
            ),
        },
        "offer_text": offer_text,
        "instruction": (
            "Analyse the offer letter above. Use the market data documents "
            "for salary / SOC comparison. Emit ONE JSON object as specified."
        ),
    }, default=str)

    if context_text:
        user_input = context_text + "\n\n---\n\n" + user_input

    parsed = await call_agent(
        agent_name="offer_analyst",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        output_schema=_OfferAnalysisBody,
    )

    json_obj = parsed.model_dump()

    fallback_citation = Citation(
        kind="url_snippet",
        url="offer_letter.pdf",
        verbatim_snippet=(json_obj.get("base_salary_gbp") or {}).get("value_text", "see attached"),
    )

    def _to_component(field: dict | None) -> Optional[OfferComponent]:
        if not field:
            return None
        return OfferComponent(
            label=field.get("label", ""),
            value_text=field.get("value_text", ""),
            citation=fallback_citation,
        )

    def _to_components(items: list[dict] | None) -> list[OfferComponent]:
        if not items:
            return []
        return [
            OfferComponent(
                label=it.get("label", ""),
                value_text=it.get("value_text", ""),
                citation=fallback_citation,
            )
            for it in items
        ]

    analysis = OfferAnalysis(
        company_name=json_obj.get("company_name", "Unknown"),
        role_title=json_obj.get("role_title"),
        base_salary_gbp=_to_component(json_obj.get("base_salary_gbp")),
        bonus=_to_component(json_obj.get("bonus")),
        equity=_to_component(json_obj.get("equity")),
        benefits=_to_components(json_obj.get("benefits")),
        notice_period=_to_component(json_obj.get("notice_period")),
        non_compete=_to_component(json_obj.get("non_compete")),
        ip_assignment=_to_component(json_obj.get("ip_assignment")),
        unusual_clauses=_to_components(json_obj.get("unusual_clauses")),
        market_comparison_note=json_obj.get("market_comparison_note"),
        flags=list(json_obj.get("flags", [])),
    )

    text_blob = " ".join(filter(None, [
        analysis.market_comparison_note or "",
        *(analysis.flags or []),
        *[c.value_text for c in analysis.benefits],
        *[c.value_text for c in analysis.unusual_clauses],
    ]))
    bp = contains_banned(text_blob)
    if bp:
        logger.warning("offer_analyst banned phrases (non-fatal): %s", bp)

    return analysis
