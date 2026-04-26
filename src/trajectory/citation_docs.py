"""Citations-API document construction helpers (PROCESS Entry 43, Workstream B).

Source-grounded agents that adopt `call_with_citations` need to build the
document list once per call and remember how each document index maps to
our domain citation shape. This module centralises that pattern so every
agent constructs documents the same way and projects citations
consistently via `Citation.from_api`.

Usage shape (cover_letter, likely_questions, etc.):

    from .citation_docs import build_documents_for_bundle
    from .schemas import Citation
    from .llm import call_with_citations

    docs, idx_maps = build_documents_for_bundle(
        bundle=research_bundle,
        career_entries=retrieved_entries,
    )
    result = await call_with_citations(
        agent_name="cover_letter",
        system_prompt=SYSTEM_PROMPT,
        user_input=user_input_text,
        documents=docs,
        ...
    )
    citations = [
        Citation.from_api(c, **idx_maps) for c in result.raw_citations
    ]
"""

from __future__ import annotations

from typing import Any, Literal

from .schemas import CareerEntry, ResearchBundle


# Document-index maps used by Citation.from_api. Pass the whole dict
# (returned alongside `documents`) into the projector with **idx_maps.
DocIndexMaps = dict[str, Any]


# Ordered set of `gov_data` paths the verdict + Phase 4 generators are
# allowed to cite. Each gets its own custom-content document so the
# model can quote it precisely.
_GOV_DATA_FIELDS: list[tuple[str, str]] = [
    # (data_field path, human title)
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
    """Lookup a dotted path against the bundle. Returns None if missing."""
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


def build_documents_for_bundle(
    *,
    bundle: ResearchBundle,
    career_entries: list[CareerEntry] | None = None,
    include_gov_data: bool = True,
    include_career_entries: bool = True,
) -> tuple[list[dict], DocIndexMaps]:
    """Build the documents list + index maps for a Citations-API call.

    Document layout (deterministic order — agents can rely on it):
      [0..N) scraped pages from research_bundle.company_research.scraped_pages
      [N..M) gov_data fields (one per resolvable field in _GOV_DATA_FIELDS)
      [M..)  career entries (one per entry, keyed by entry_id in title)

    Returns:
      documents — passable directly to `call_with_citations(documents=...)`
      idx_maps  — dict of url_by_doc_index, kind_by_doc_index,
                  gov_field_by_doc_index, entry_id_by_doc_index. Pass via
                  `Citation.from_api(raw, **idx_maps)`.
    """
    documents: list[dict] = []
    url_by_doc_index: dict[int, str] = {}
    kind_by_doc_index: dict[int, Literal["url_snippet", "gov_data", "career_entry"]] = {}
    gov_field_by_doc_index: dict[int, str] = {}
    entry_id_by_doc_index: dict[int, str] = {}

    # 1. Scraped pages — citations attach to substrings of `text`.
    for page in bundle.company_research.scraped_pages:
        idx = len(documents)
        documents.append({
            "type": "text",
            "text": page.text,
            "title": page.title or page.url,
            "context": f"Scraped page from {page.url}",
        })
        url_by_doc_index[idx] = page.url
        kind_by_doc_index[idx] = "url_snippet"

    # 2. Gov_data fields — one custom-content document per resolvable
    # field. The model cites by quoting the value text; we project that
    # back to the gov_data kind via gov_field_by_doc_index.
    if include_gov_data:
        for field_path, title in _GOV_DATA_FIELDS:
            value = _resolve_dotted(field_path, bundle)
            if value is None:
                continue
            value_text = str(value)
            idx = len(documents)
            documents.append({
                "type": "custom",
                "blocks": [{"text": value_text}],
                "title": f"{title} ({field_path})",
                "context": f"Gov-data field {field_path}",
            })
            kind_by_doc_index[idx] = "gov_data"
            gov_field_by_doc_index[idx] = field_path

    # 3. Career entries.
    if include_career_entries and career_entries:
        for entry in career_entries:
            idx = len(documents)
            documents.append({
                "type": "custom",
                "blocks": [{"text": entry.raw_text}],
                "title": f"career_entry:{entry.entry_id}",
                "context": f"Career entry kind={entry.kind}",
            })
            kind_by_doc_index[idx] = "career_entry"
            entry_id_by_doc_index[idx] = entry.entry_id

    idx_maps: DocIndexMaps = {
        "url_by_doc_index": url_by_doc_index,
        "kind_by_doc_index": kind_by_doc_index,
        "gov_field_by_doc_index": gov_field_by_doc_index,
        "entry_id_by_doc_index": entry_id_by_doc_index,
    }
    return documents, idx_maps
