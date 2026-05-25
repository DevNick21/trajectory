"""Inline document context builder for citation-grounded agents.

Replaces the old Anthropic Citations API document block format. Instead of
sending separate document blocks per the Citations API, we inline all source
context into the user prompt so the model can ground its output against
specific document indices. Agents reference documents by index and emit
citations as structured arrays.

Usage:
    from .citation_docs import build_document_context

    context, citation_map = build_document_context(
        bundle=research_bundle,
        career_entries=retrieved_entries,
    )
    user_input = f"{context}\n\n---\n\n{user_input}"
    # Model emits citations like: [{"kind": "url_snippet", "url": "...", "text": "..."}]
"""

from __future__ import annotations

from typing import Any

from .schemas import CareerEntry, Citation, ResearchBundle


DocIndexMap = dict[int, dict[str, Any]]

# Ordered set of gov_data fields the model is allowed to cite.
_GOV_DATA_FIELDS: list[tuple[str, str]] = [
    ("sponsor_status.status", "Sponsor Register status"),
    ("sponsor_status.matched_name", "Sponsor Register matched name"),
    ("sponsor_status.rating", "Sponsor Register rating"),
    ("companies_house.status", "Companies House status"),
    ("companies_house.accounts_overdue", "Companies House: accounts overdue"),
    ("companies_house.last_accounts_date", "Companies House: last accounts date"),
    ("soc_check.soc_code", "SOC code"),
    ("soc_check.going_rate_gbp", "SOC going rate (GBP)"),
    ("soc_check.below_threshold", "SOC: salary below threshold"),
    ("soc_check.on_appendix_skilled_occupations", "SOC: on Appendix Skilled Occupations"),
    ("ghost_job.probability", "Ghost-job probability"),
    ("ghost_job.confidence", "Ghost-job confidence"),
    ("salary_signals.ashe.p10", "ASHE p10"),
    ("salary_signals.ashe.p50", "ASHE p50"),
    ("salary_signals.ashe.p90", "ASHE p90"),
    ("extracted_jd.role_title", "JD role title"),
    ("extracted_jd.location", "JD location"),
    ("extracted_jd.remote_policy", "JD remote policy"),
    ("company_research.company_name", "Company name"),
]


def _resolve_dotted(path: str, bundle: ResearchBundle) -> Any:
    if "." not in path:
        return None
    root, rest = path.split(".", 1)
    source: Any = None
    if root in ("sponsor_status", "sponsor_register"):
        source = bundle.sponsor_status
    elif root == "companies_house":
        source = bundle.companies_house
    elif root in ("soc_check", "going_rates"):
        source = bundle.soc_check
    elif root in ("ghost_job", "ghost_job_assessment"):
        source = bundle.ghost_job
    elif root == "salary_signals":
        source = bundle.salary_signals
    elif root in ("red_flags", "red_flags_report"):
        source = bundle.red_flags
    elif root in ("extracted_jd", "jd"):
        source = bundle.extracted_jd
    elif root == "company_research":
        source = bundle.company_research
    if source is None:
        return None
    current = source
    for part in rest.split("."):
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def build_document_context(
    *,
    bundle: ResearchBundle,
    career_entries: list[CareerEntry] | None = None,
    include_gov_data: bool = True,
    include_career_entries: bool = True,
) -> tuple[str, DocIndexMap]:
    """Build inline context text + citation index map.

    Returns:
      context_text — inline Markdown text to prepend to the user prompt.
      citation_map — dict of doc_index → {kind, url, field, entry_id} for
                     projecting model-emitted citations.
    """
    parts: list[str] = []
    citation_map: DocIndexMap = {}
    idx = 0

    # 1. Scraped pages
    for page in bundle.company_research.scraped_pages:
        title = page.title or page.url
        parts.append(f"## Document {idx}: {title}\n"
                     f"Source: {page.url}\n\n{page.text}\n")
        citation_map[idx] = {"kind": "url_snippet", "url": page.url}
        idx += 1

    # 2. Gov data fields
    if include_gov_data:
        for field_path, title in _GOV_DATA_FIELDS:
            value = _resolve_dotted(field_path, bundle)
            if value is None:
                continue
            parts.append(f"## Document {idx}: {title}\n"
                         f"Field: {field_path}\n\n{value}\n")
            citation_map[idx] = {"kind": "gov_data", "gov_field": field_path}
            idx += 1

    # 3. Career entries
    if include_career_entries and career_entries:
        for entry in career_entries:
            parts.append(f"## Document {idx}: Career Entry ({entry.kind})\n"
                         f"Entry ID: {entry.entry_id}\n\n{entry.raw_text}\n")
            citation_map[idx] = {"kind": "career_entry", "entry_id": entry.entry_id}
            idx += 1

    context = (
        "Below are source documents for citation-grounded output. Every "
        "factual claim must cite a document index from this list.\n\n"
        + "\n".join(parts)
    )
    return context, citation_map
