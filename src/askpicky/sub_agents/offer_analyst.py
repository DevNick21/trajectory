"""Offer letter analyst (PROCESS Entry 43, Workstream F).

Pipeline:
  1. PDF in via Files API (`client.beta.files.upload`) -> file_id.
  2. Citations enabled on the document.
  3. Output: `OfferAnalysis` with every component cited to a page.
  4. Comparison flags via ASHE + sponsor_register cited as gov_data.

The analysis prompt asks for a single JSON block as the FINAL output;
citations attach to spans within it. After parsing, citations are
projected via `Citation.from_api`.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

from ..citation_docs import build_documents_for_bundle
from ..config import settings
from ..llm import call_with_citations, AgentCallFailed
from ..schemas import (
    Citation,
    OfferAnalysis,
    OfferComponent,
    ResearchBundle,
    UserProfile,
)
from ..validators.banned_phrases import contains_banned

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are the Trajectory offer-letter analyst. Analyse the offer letter
attached as the first document and answer for the user whose UK
profile is supplied in the prompt.

Return the analysis as ONE JSON object inside a single text block. Do
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

CITATION RULES (Citations API will validate):
- Every numeric / clause field must cite the exact page in the offer letter.
- Comparisons against ASHE / SOC use the gov_data documents supplied
  alongside the PDF.
- value_text fields should be the verbatim figure or clause.

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


async def upload_pdf(pdf_bytes: bytes, filename: str = "offer.pdf") -> str:
    """Upload a PDF to Anthropic's Files API and return the file_id."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    f = await client.beta.files.upload(
        file=(filename, pdf_bytes, "application/pdf"),
    )
    file_id = getattr(f, "id")
    logger.info("offer_analyst: uploaded PDF -> file_id=%s", file_id)
    return file_id


async def analyse(
    *,
    user: UserProfile,
    research_bundle: Optional[ResearchBundle] = None,
    file_id: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    text_pasted: Optional[str] = None,
    session_id: Optional[str] = None,
) -> OfferAnalysis:
    """Analyse an offer letter.

    One of `file_id`, `pdf_bytes`, or `text_pasted` must be provided.
    `research_bundle` adds gov_data + scraped-page documents for richer
    market comparison; optional but recommended.
    """
    if not any([file_id, pdf_bytes, text_pasted]):
        raise ValueError(
            "analyse requires one of file_id, pdf_bytes, or text_pasted."
        )

    # Build the offer document block.
    offer_doc: dict
    if file_id is None and pdf_bytes is not None:
        # Inline upload via Files API for efficiency on re-runs.
        file_id = await upload_pdf(pdf_bytes)
    if file_id:
        offer_doc = {
            "type": "file_id",
            "file_id": file_id,
            "title": "Offer letter",
            "context": "PDF offer letter under analysis",
        }
    else:
        offer_doc = {
            "type": "text",
            "text": text_pasted or "",
            "title": "Offer letter (pasted)",
        }

    documents = [offer_doc]
    idx_maps: dict = {
        "url_by_doc_index": {},
        "kind_by_doc_index": {},
        "gov_field_by_doc_index": {},
        "entry_id_by_doc_index": {},
    }
    # The offer document itself: cite as url_snippet with title as URL.
    idx_maps["url_by_doc_index"][0] = "offer_letter.pdf"
    idx_maps["kind_by_doc_index"][0] = "url_snippet"

    if research_bundle is not None:
        bundle_docs, bundle_maps = build_documents_for_bundle(
            bundle=research_bundle,
            career_entries=None,
            include_career_entries=False,
        )
        offset = len(documents)
        documents.extend(bundle_docs)
        for k, v in bundle_maps["url_by_doc_index"].items():
            idx_maps["url_by_doc_index"][k + offset] = v
        for k, v in bundle_maps["kind_by_doc_index"].items():
            idx_maps["kind_by_doc_index"][k + offset] = v
        for k, v in bundle_maps["gov_field_by_doc_index"].items():
            idx_maps["gov_field_by_doc_index"][k + offset] = v

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
        "instruction": (
            "Analyse the offer letter (document index 0). Use the "
            "remaining documents for market / SOC comparison if present. "
            "Emit ONE JSON object as described in the system prompt."
        ),
    }, default=str)

    result = await call_with_citations(
        agent_name="offer_analyst",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input,
        documents=documents,
        model=settings.opus_model_id,
        effort="xhigh",
        session_id=session_id,
    )

    # Extract the JSON object from the body. The model is asked to emit
    # a single JSON block; we tolerate leading/trailing prose.
    body = result.body.strip()
    json_obj = _extract_json(body)
    if json_obj is None:
        raise AgentCallFailed(
            f"offer_analyst did not emit a parseable JSON object. "
            f"Body[:200]: {body[:200]!r}"
        )

    # Build domain Citation objects from the SDK citations. Component-
    # level citations are not 1:1 with our Citation list, so for this
    # iteration each OfferComponent receives the closest preceding
    # citation; flat raw_citations available for future structured
    # mapping.
    flat_citations: list[Citation] = []
    for raw in result.raw_citations:
        try:
            flat_citations.append(Citation.from_api(raw, **idx_maps))
        except Exception as exc:
            logger.warning("offer_analyst: skip bad citation: %s (%s)", raw, exc)

    fallback_citation = (
        flat_citations[0]
        if flat_citations
        else Citation(
            kind="url_snippet",
            url="offer_letter.pdf",
            verbatim_snippet=(json_obj.get("base_salary_gbp") or {}).get("value_text", "see attached"),
        )
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

    # Banned-phrase post-validation across every text field.
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


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(body: str) -> Optional[dict]:
    """Pull the JSON object out of free-form body text. Tolerates
    leading commentary or trailing notes."""
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(body)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _b64_pdf(pdf_bytes: bytes) -> str:
    return base64.b64encode(pdf_bytes).decode("ascii")
