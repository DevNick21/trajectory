"""Citation resolution + verification.

CLAUDE.md Rule 1 — every claim in generated output must resolve to:
  - a scraped URL + verbatim snippet in the research bundle, or
  - a specific gov.uk data field + value, or
  - an existing `CareerEntry.entry_id`.

`validate_output(output, ctx)` walks the Pydantic tree, collects every
`Citation`, and returns a list of human-readable failure descriptions.
Empty list = accepted.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel

from ..schemas import (
    CareerEntry,
    Citation,
    CompaniesHouseSnapshot,
    ResearchBundle,
    SocCheckResult,
    SponsorStatus,
)


_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Whitespace-tolerant comparison for verbatim snippets."""
    return _WS_RE.sub(" ", text).strip().lower()


# ---------------------------------------------------------------------------
# Context for validation
# ---------------------------------------------------------------------------


class ValidationContext(BaseModel):
    """Everything the validator needs to resolve citations.

    `career_store_entries` is pre-loaded to avoid async in the walk. Callers
    resolve `CareerEntry.entry_id`s from storage and pass them in.
    """

    research_bundle: Optional[ResearchBundle] = None
    career_store_entries: dict[str, CareerEntry]

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Per-kind validators
# ---------------------------------------------------------------------------


def _validate_url_snippet(c: Citation, ctx: ValidationContext) -> Optional[str]:
    if not c.url or not c.verbatim_snippet:
        return "url_snippet citation missing url or verbatim_snippet"
    if ctx.research_bundle is None:
        return "url_snippet citation but no research bundle in context"

    # A snippet quoting `[REDACTED: <pattern>]` means the agent cited
    # content the Content Shield stripped — the "evidence" is a redaction
    # marker, not real supporting text. Reject so the retry loop forces
    # a different citation.
    if "[REDACTED:" in c.verbatim_snippet:
        return (
            f"url_snippet citation: verbatim text is a Content Shield "
            f"redaction marker, not real evidence. Pick a snippet from "
            f"unredacted source text at {c.url}."
        )

    snippet_norm = _normalise(c.verbatim_snippet)
    for page in ctx.research_bundle.company_research.scraped_pages:
        if page.url == c.url and snippet_norm in _normalise(page.text):
            return None
    return (
        f"url_snippet citation: verbatim text not found at {c.url}. "
        "Either the URL is not in scraped_pages or the snippet was paraphrased."
    )


def _validate_gov_data(c: Citation, ctx: ValidationContext) -> Optional[str]:
    if not c.data_field or c.data_value is None:
        return "gov_data citation missing data_field or data_value"
    if ctx.research_bundle is None:
        return "gov_data citation but no research bundle in context"

    actual = _resolve_gov_field(c.data_field, ctx.research_bundle)
    if actual is None:
        # Build a helper message listing valid leaves under the cited
        # root, so the next retry can swap to a real field instead of
        # making up another non-existent one. PROCESS Entry 47: live
        # `salary_strategist` runs occasionally cite a hallucinated
        # field path (`salary_signals.aggregated_postings`) and exhaust
        # all retries because the previous error message just said
        # "not resolvable" with no hint of what IS resolvable.
        valid = _enumerate_valid_fields(c.data_field, ctx.research_bundle)
        if valid:
            return (
                f"gov_data citation: field {c.data_field!r} not "
                f"resolvable in research bundle. Valid fields under this "
                f"root: {', '.join(valid)}"
            )
        return (
            f"gov_data citation: field {c.data_field!r} not resolvable "
            "in research bundle (root unknown — use one of "
            "sponsor_register / companies_house / soc_check / "
            "ghost_job / salary_signals / red_flags / "
            "extracted_jd / company_research)"
        )

    claimed = _normalise(str(c.data_value))

    # List-typed fields (specificity_signals, vagueness_signals, sic_codes,
    # required_skills, etc.): accept the citation if the claimed value
    # matches any list element. Citing a single signal from a list is the
    # natural form for the verdict / generators.
    if isinstance(actual, list):
        actual_norm = [_normalise(str(item)) for item in actual]
        if claimed in actual_norm:
            return None
        return (
            f"gov_data citation: field {c.data_field!r} list does not contain "
            f"{c.data_value!r}; values are {actual!r}"
        )

    actual_norm = _normalise(str(actual))
    if actual_norm == claimed:
        return None

    # Long free-text fields (jd_text_full, descriptions, etc.) — accept
    # the citation if the claimed value is a verbatim substring of the
    # field's full content. Without this the model has to quote the
    # entire JD body to cite any sentence from it.
    if len(actual_norm) > 200 and claimed in actual_norm:
        return None

    return (
        f"gov_data citation: field {c.data_field!r} has value {actual!r} "
        f"but citation claims {c.data_value!r}"
    )


def _resolve_gov_field(path: str, bundle: ResearchBundle) -> Any:
    """Resolve dotted paths against the research bundle.

    Supported roots — each maps to a resolved field on the bundle that
    the verdict / Phase 4 generators can cite as a discrete value:

      - sponsor_register.*    → bundle.sponsor_status
      - companies_house.*     → bundle.companies_house
      - soc_check.*           → bundle.soc_check
      - going_rates.*         → bundle.soc_check (convenience alias)
      - ghost_job.*           → bundle.ghost_job
      - salary_signals.*      → bundle.salary_signals
      - red_flags.*           → bundle.red_flags
      - extracted_jd.*        → bundle.extracted_jd  (scraped JD fields
                                like remote_policy, salary_band, location)
      - company_research.*    → bundle.company_research  (company_name,
                                careers_page_url, not_on_careers_page)

    `gov_data` is a slight misnomer for the JD/company roots — they're
    sourced from scraping rather than gov.uk — but the citation kind
    captures "this points at a discrete structured field" rather than a
    free-text snippet, which is the right semantic for these fields.
    """
    if "." not in path:
        return None
    root, rest = path.split(".", 1)
    source: Optional[BaseModel] = None
    # Accept both the gov-doc-style root (`sponsor_register`) and the
    # bundle-attribute-style root (`sponsor_status`) since the model
    # picks whichever feels more natural. Same for ghost_job_assessment,
    # salary_signals, etc.
    if root in ("sponsor_register", "sponsor_status"):
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

    # Walk dotted attrs on the model.
    current: Any = source
    for part in rest.split("."):
        if isinstance(current, BaseModel):
            if not hasattr(current, part):
                return None
            current = getattr(current, part)
        elif isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def _enumerate_valid_fields(path: str, bundle: ResearchBundle) -> list[str]:
    """Given a citation path like `salary_signals.aggregated_postings`
    that didn't resolve, list the actual leaf field names available
    under that root. Returns [] when the root itself is unrecognised.
    Used as retry feedback for the model when it hallucinates a field."""
    if "." not in path:
        return []
    root = path.split(".", 1)[0]
    source: Optional[BaseModel] = None
    if root in ("sponsor_register", "sponsor_status"):
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
    if source is None or not isinstance(source, BaseModel):
        return []
    return [f"{root}.{name}" for name in source.__class__.model_fields.keys()]


def _validate_career_entry(c: Citation, ctx: ValidationContext) -> Optional[str]:
    if not c.entry_id:
        return "career_entry citation missing entry_id"
    if c.entry_id not in ctx.career_store_entries:
        return (
            f"career_entry citation: entry_id {c.entry_id!r} not found "
            f"in career store. Available entry_ids "
            f"({len(ctx.career_store_entries)} total): "
            f"{sorted(list(ctx.career_store_entries))[:8]}"
            + ("..." if len(ctx.career_store_entries) > 8 else "")
        )
    return None


def validate_citation(c: Citation, ctx: ValidationContext) -> tuple[bool, str]:
    """Returns (ok, reason-if-not-ok)."""
    if c.kind == "url_snippet":
        err = _validate_url_snippet(c, ctx)
    elif c.kind == "gov_data":
        err = _validate_gov_data(c, ctx)
    elif c.kind == "career_entry":
        err = _validate_career_entry(c, ctx)
    else:
        err = f"unknown citation kind: {c.kind}"
    return (err is None, err or "")


# ---------------------------------------------------------------------------
# Tree walk
# ---------------------------------------------------------------------------


def extract_all_citations(output: BaseModel) -> list[Citation]:
    """Walk every field of `output` and collect Citation instances.

    Handles nested BaseModels, lists, tuples, dicts.
    """
    found: list[Citation] = []
    _walk(output, found)
    return found


def _walk(obj: Any, into: list[Citation]) -> None:
    if isinstance(obj, Citation):
        into.append(obj)
        return
    if isinstance(obj, BaseModel):
        for name in obj.__class__.model_fields:
            _walk(getattr(obj, name), into)
        return
    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            _walk(item, into)
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, into)
        return
    # primitives: no-op


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def validate_output(output: BaseModel, ctx: ValidationContext) -> list[str]:
    """Return a list of human-readable failure descriptions.

    An empty list means all citations resolved.
    """
    failures: list[str] = []
    citations = extract_all_citations(output)
    for i, c in enumerate(citations):
        ok, reason = validate_citation(c, ctx)
        if not ok:
            failures.append(f"[citation #{i}] {reason}")
    return failures


# ---------------------------------------------------------------------------
# Convenience builders
# ---------------------------------------------------------------------------


async def build_context(
    research_bundle: Optional[ResearchBundle],
    user_id: str,
    career_entries: Optional[list[CareerEntry]] = None,
) -> ValidationContext:
    """Build a ValidationContext from a bundle + an explicit list of entries.

    If `career_entries` is None, the caller should pre-load the relevant
    entries from storage — the validator does not reach into storage itself
    (keeps it pure + sync).
    """
    entries_map = {e.entry_id: e for e in (career_entries or [])}
    return ValidationContext(
        research_bundle=research_bundle,
        career_store_entries=entries_map,
    )


# Re-export a couple of types the caller often wants.
__all__ = [
    "ValidationContext",
    "validate_citation",
    "validate_output",
    "extract_all_citations",
    "build_context",
    "CompaniesHouseSnapshot",
    "SponsorStatus",
    "SocCheckResult",
]
