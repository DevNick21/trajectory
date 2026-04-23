"""JSON-LD Tier 0 extractor.

Pre-LLM parser for Schema.org `JobPosting` JSON-LD blocks. Runs BEFORE
the Sonnet JD extractor so authoritative fields (datePosted, baseSalary,
etc.) are surfaced as ground truth rather than inferred from body text.

Consumers (indirectly):
  - ghost_job_detector._stale_signal — benefits from accurate posted_date.
  - salary_data — benefits from accurate posted band on sites that ship
    structured salary but natural-language-absent bands.

Hard constraints (see files/03-jsonld-extractor.md):
  - Pure function, no I/O. Never raises. Malformed JSON → None.
  - Not cited in verdicts — this is an input hint to the Sonnet extractor,
    not a citable source. `JsonLdExtraction` is an internal intermediate,
    not stored in the research bundle.
  - GBP-only. Non-GBP / missing currency → salary fields stay None.
  - Does not normalise hourly/daily to annual — surfaces raw numbers
    with the correct `salary_period`. Normalisation lives downstream.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Optional

from dateutil import parser as dateparser

from ..schemas import JsonLdExtraction
from ..validators.content_shield import _strip_invisible

logger = logging.getLogger(__name__)


_REDACTED_MARKER = "[REDACTED:"

_UNIT_TEXT_MAP = {
    "YEAR": "annual",
    "MONTH": "monthly",
    "WEEK": None,  # not supported; log and skip
    "DAY": "daily",
    "HOUR": "hourly",
}


def extract_jsonld_jobposting(raw_html: str) -> Optional[JsonLdExtraction]:
    """Parse Schema.org JobPosting JSON-LD from raw HTML.

    Returns None if no parseable JobPosting block is found.
    Never raises — malformed JSON-LD returns None, not an exception.
    """
    if not raw_html:
        return None

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_html, "html.parser")
    except Exception as exc:  # pragma: no cover — defensive only
        logger.debug("BeautifulSoup parse failed: %r", exc)
        return None

    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    if not scripts:
        return None

    job_postings: list[dict[str, Any]] = []
    for tag in scripts:
        raw_text = tag.string or tag.get_text() or ""
        if not raw_text.strip():
            continue
        try:
            parsed = json.loads(raw_text)
        except (ValueError, TypeError) as exc:
            logger.debug("Malformed JSON-LD block skipped: %r", exc)
            continue
        job_postings.extend(_find_jobpostings(parsed))

    if not job_postings:
        return None

    if len(job_postings) > 1:
        logger.warning(
            "Multiple JobPosting JSON-LD blocks found (%d); using first",
            len(job_postings),
        )

    return _build_extraction(job_postings[0])


def _find_jobpostings(node: Any) -> list[dict[str, Any]]:
    """Recursively locate all `@type: JobPosting` dicts inside a parsed
    JSON-LD value. Handles single-object, array, @graph, and nested
    Organization-wrapping shapes.
    """
    out: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_find_jobpostings(item))
        return out
    if not isinstance(node, dict):
        return out

    node_type = node.get("@type")
    if _type_matches(node_type, "JobPosting"):
        out.append(node)

    graph = node.get("@graph")
    if graph is not None:
        out.extend(_find_jobpostings(graph))

    return out


def _type_matches(node_type: Any, target: str) -> bool:
    """Schema.org `@type` is sometimes a string, sometimes a list."""
    if isinstance(node_type, str):
        return node_type == target
    if isinstance(node_type, list):
        return target in node_type
    return False


def _build_extraction(job: dict[str, Any]) -> JsonLdExtraction:
    raw_fields = sorted(k for k in job.keys() if not k.startswith("@"))

    title = _clean_str(_unwrap(job.get("title")))
    employment_type = _first_str(job.get("employmentType"))
    hiring_org = _clean_str(_nested(job, "hiringOrganization", "name"))
    date_posted = _parse_date(_unwrap(job.get("datePosted")))
    valid_through = _parse_date(_unwrap(job.get("validThrough")))
    location = _build_location(job.get("jobLocation"))
    salary_min, salary_max, salary_period = _parse_salary(job.get("baseSalary"))
    description_plain = _strip_html(_clean_str(_unwrap(job.get("description"))))

    return JsonLdExtraction(
        title=title,
        date_posted=date_posted,
        valid_through=valid_through,
        hiring_organization_name=hiring_org,
        employment_type=employment_type,
        location=location,
        salary_min_gbp=salary_min,
        salary_max_gbp=salary_max,
        salary_period=salary_period,
        description_plain=description_plain,
        raw_fields_present=raw_fields,
    )


def _unwrap(value: Any) -> Any:
    """Schema.org sometimes wraps primitives as `{"@value": "..."}`. Unwrap."""
    if isinstance(value, dict) and "@value" in value:
        return value.get("@value")
    return value


def _clean_str(value: Any) -> Optional[str]:
    """String-normalise a JSON-LD value: unwrap, strip invisible chars,
    reject shield redaction markers, coerce empty → None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = _strip_invisible(value).strip()
    if not cleaned:
        return None
    if _REDACTED_MARKER in cleaned:
        return None
    return cleaned


def _first_str(value: Any) -> Optional[str]:
    """`employmentType` may be a string or an array of strings; take the
    first present."""
    value = _unwrap(value)
    if isinstance(value, list):
        for item in value:
            cleaned = _clean_str(_unwrap(item))
            if cleaned:
                return cleaned
        return None
    return _clean_str(value)


def _parse_date(value: Any) -> Optional[date]:
    """ISO 8601 date or datetime → `date`. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = _strip_invisible(value).strip()
    if not text or _REDACTED_MARKER in text:
        return None
    try:
        parsed = dateparser.isoparse(text)
    except (ValueError, TypeError) as exc:
        logger.debug("datePosted parse failed for %r: %r", text, exc)
        return None
    return parsed.date()


def _nested(obj: Any, *path: str) -> Any:
    """Safely walk a nested dict path; returns None on any miss."""
    cur: Any = obj
    for key in path:
        cur = _unwrap(cur)
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return _unwrap(cur)


def _build_location(node: Any) -> Optional[str]:
    """Flatten `jobLocation.address` into a 'City, Country' string.

    `jobLocation` may be a dict, a list of dicts, or missing. Take the
    first locatable entry; skip any whose address is unusable.
    """
    node = _unwrap(node)
    candidates: list[Any] = []
    if isinstance(node, list):
        candidates = node
    elif isinstance(node, dict):
        candidates = [node]
    else:
        return None

    for entry in candidates:
        entry = _unwrap(entry)
        if not isinstance(entry, dict):
            continue
        address = _unwrap(entry.get("address"))
        if not isinstance(address, dict):
            continue
        city = _clean_str(_unwrap(address.get("addressLocality")))
        country = _clean_str(_unwrap(address.get("addressCountry")))
        # addressCountry can be nested as `{"name": "United Kingdom"}`.
        if country is None:
            country_obj = _unwrap(address.get("addressCountry"))
            if isinstance(country_obj, dict):
                country = _clean_str(_unwrap(country_obj.get("name")))
        if city and country:
            return f"{city}, {country}"
        if city:
            return city
        if country:
            return country
    return None


def _parse_salary(node: Any) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Extract (min_gbp, max_gbp, period) from a `baseSalary` block.

    Returns (None, None, None) when currency is not GBP, the block is
    missing, or the numbers cannot be parsed.
    """
    node = _unwrap(node)
    if not isinstance(node, dict):
        return None, None, None

    currency = _clean_str(_unwrap(node.get("currency")))
    if currency is None:
        # Some sites put the currency on the inner QuantitativeValue.
        value_block = _unwrap(node.get("value"))
        if isinstance(value_block, dict):
            currency = _clean_str(_unwrap(value_block.get("currency")))

    if currency and currency.upper() != "GBP":
        logger.debug("Skipping non-GBP baseSalary (currency=%s)", currency)
        return None, None, None

    value_block = _unwrap(node.get("value"))
    min_val: Any = None
    max_val: Any = None
    unit_text: Any = None

    if isinstance(value_block, dict):
        min_val = _unwrap(value_block.get("minValue"))
        max_val = _unwrap(value_block.get("maxValue"))
        unit_text = _unwrap(value_block.get("unitText"))
        # Single `value` instead of min/max.
        if min_val is None and max_val is None:
            single = _unwrap(value_block.get("value"))
            if single is not None:
                min_val = single
                max_val = single
    else:
        # `baseSalary` sometimes is the numeric itself.
        if isinstance(value_block, (int, float, str)):
            min_val = value_block
            max_val = value_block
        unit_text = _unwrap(node.get("unitText"))

    salary_min = _coerce_int(min_val)
    salary_max = _coerce_int(max_val)
    period = _normalise_unit_text(unit_text)

    if salary_min is None and salary_max is None:
        return None, None, None

    return salary_min, salary_max, period


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort integer coercion. Strings like '75000.00' or '£75,000'
    are tolerated; non-numeric returns None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (ValueError, OverflowError):
            return None
    if isinstance(value, str):
        text = _strip_invisible(value).strip()
        if not text or _REDACTED_MARKER in text:
            return None
        stripped = text.replace(",", "").replace("£", "").replace("$", "").strip()
        try:
            return int(float(stripped))
        except (ValueError, TypeError):
            return None
    return None


def _normalise_unit_text(value: Any) -> Optional[str]:
    """Schema.org `unitText` → our `salary_period` enum. Missing → 'annual'
    per Schema.org default. WEEK is not supported; returns None.
    """
    if value is None:
        return "annual"
    if not isinstance(value, str):
        return "annual"
    key = _strip_invisible(value).strip().upper()
    if not key:
        return "annual"
    mapped = _UNIT_TEXT_MAP.get(key)
    if mapped is None and key == "WEEK":
        logger.debug("Weekly salary period skipped (unsupported)")
        return None
    if mapped is None:
        # Unknown unit → treat conservatively as missing period rather than
        # guessing annual and misleading downstream consumers.
        logger.debug("Unknown unitText %r; period left unset", value)
        return None
    return mapped


def _strip_html(value: Optional[str]) -> Optional[str]:
    """JobPosting.description is sometimes an HTML blob. Flatten to text."""
    if value is None:
        return None
    if "<" not in value:
        return value
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(value, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        return text or None
    except Exception:  # pragma: no cover
        return value
