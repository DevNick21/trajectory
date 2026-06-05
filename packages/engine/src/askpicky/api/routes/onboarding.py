"""Web onboarding endpoints.

Two endpoints, both stateless per ADR-003 (wizard state lives in
browser localStorage, not in the server):

  - POST /api/onboarding/parse     — helper for future per-stage UX
  - POST /api/onboarding/finalise  — write UserProfile + CareerEntries

The web wizard does not run LLM extraction during finalise. It stores
typed fields plus deterministic preference splits so onboarding stays
fast; richer extraction belongs in background memory jobs or explicit
user-requested flows.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ...schemas import CareerEntry, UserProfile, VisaStatus
from ...storage import Storage
from ..dependencies import get_current_user_id, get_storage
from ..schemas import (
    OnboardingFinaliseRequest,
    OnboardingFinaliseResponse,
    OnboardingParseRequest,
)

router = APIRouter()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /api/onboarding/parse
# ---------------------------------------------------------------------------


@router.post("/onboarding/parse")
async def parse(
    req: OnboardingParseRequest,
    _user_id: str = Depends(get_current_user_id),
) -> dict:
    """Run the onboarding parser for a single free-text stage.

    Returns the raw ParseResult shape (status + fields + follow_up).
    The wizard can use this to show a parsed summary before the user
    moves on, or display a clarification question on
    needs_clarification. Wave 9 wizard calls /finalise only; this
    endpoint is exposed for future richer UX.
    """
    from ...sub_agents.onboarding_parser import parse_stage

    result = await parse_stage(req.stage, req.text)
    if result is None:
        return {"status": "parsed"}
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# POST /api/onboarding/finalise
# ---------------------------------------------------------------------------


_LIST_SPLIT_RE = re.compile(r"(?:\r?\n|;|•|·| - |\s\|\s)+")


def _split_user_list(text: str) -> list[str]:
    """Split short preference text without an LLM call."""
    cleaned = text.strip()
    if not cleaned:
        return []
    parts = [p.strip(" \t\r\n-•·") for p in _LIST_SPLIT_RE.split(cleaned)]
    parts = [p for p in parts if p]
    if len(parts) == 1 and "," in cleaned and len(cleaned) <= 180:
        parts = [p.strip(" \t\r\n-•·") for p in cleaned.split(",")]
        parts = [p for p in parts if p]
    return parts or [cleaned]


def _derive_motivations_and_drains(raw_text: str) -> tuple[list[str], list[str]]:
    motivations = _split_user_list(raw_text)
    return motivations, []


def _derive_deal_breakers_and_signals(
    raw_text: str, extra_signals_text: str,
) -> tuple[list[str], list[str]]:
    deal_breakers = _split_user_list(raw_text)
    good_role_signals = _split_user_list(extra_signals_text)
    return deal_breakers, good_role_signals


def _derive_visa_status(req: OnboardingFinaliseRequest) -> Optional[VisaStatus]:
    if req.user_type != "visa_holder":
        return None
    route = req.visa_route or "other"
    expiry = req.visa_expiry
    if expiry is None or expiry < date.today():
        # an expired / missing visa date shouldn't flag the user as
        # already-expired in the urgency scorer.
        expiry = date(date.today().year + 2, 12, 31)
    return VisaStatus(route=route, expiry_date=expiry)


def _derive_search_started_date(req: OnboardingFinaliseRequest) -> date:
    months = req.search_duration_months
    if months and months > 0:
        return date.today().replace(day=1) - timedelta(days=30 * months)
    return date.today()


@router.post(
    "/onboarding/finalise",
    response_model=OnboardingFinaliseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def finalise(
    req: OnboardingFinaliseRequest,
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> OnboardingFinaliseResponse:
    """Write UserProfile + CareerEntries.

    No LLM parsers run here. All writes share the same `now` timestamp so
    downstream queries can correlate them.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    motivations, drains = _derive_motivations_and_drains(req.motivations_text)
    deal_breakers, good_role_signals = _derive_deal_breakers_and_signals(
        req.deal_breakers_text,
        req.good_role_signals_text,
    )

    # Finalise is deterministic; life constraints come from the wizard.
    life_constraints = list(req.life_constraints) + drains

    # --- UserProfile ----------------------------------------------------
    user = UserProfile(
        user_id=user_id,
        name=req.name.strip() or "User",
        user_type=req.user_type,
        visa_status=_derive_visa_status(req),
        nationality=req.nationality,
        base_location=req.base_location.strip() or "London",
        salary_floor=req.salary_floor,
        salary_target=req.salary_target,
        motivations=motivations,
        deal_breakers=deal_breakers,
        good_role_signals=good_role_signals,
        life_constraints=life_constraints,
        search_started_date=_derive_search_started_date(req),
        current_employment=req.current_employment,
        writing_style_profile_id=None,
        created_at=now,
        updated_at=now,
    )
    await storage.save_user_profile(user)

    # --- Career entries --------------------------------------------------
    entries_written = 0

    narrative = req.career_narrative.strip()
    if not narrative:
        parts = []
        if req.name:
            parts.append(req.name)
        if req.base_location:
            parts.append(f"based in {req.base_location}")
        if req.current_employment:
            label = {
                "EMPLOYED": "currently employed",
                "UNEMPLOYED": "currently between roles",
                "NOTICE_PERIOD": "currently serving notice",
            }.get(req.current_employment, "")
            if label:
                parts.append(label)
        if req.salary_floor > 0:
            parts.append(f"seeking roles from £{req.salary_floor:,}")
        if parts:
            narrative = "Career profile: " + ". ".join(parts) + "."

    pending_entries: list[CareerEntry] = []

    if narrative:
        pending_entries.append(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="conversation",
            raw_text=narrative,
            created_at=now,
        ))

    for text in motivations:
        pending_entries.append(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="motivation",
            raw_text=text,
            created_at=now,
        ))

    for text in deal_breakers:
        pending_entries.append(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="deal_breaker",
            raw_text=text,
            created_at=now,
        ))

    for text in good_role_signals:
        pending_entries.append(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="good_role_signal",
            raw_text=text,
            created_at=now,
        ))

    if pending_entries:
        await storage.insert_career_entries_batch(pending_entries)
        entries_written = len(pending_entries)

    log.info(
        "onboarding finalised for %s: entries=%d",
        user_id, entries_written,
    )

    return OnboardingFinaliseResponse(
        user_id=user_id,
        career_entries_written=entries_written,
    )


# ---------------------------------------------------------------------------
# POST /api/onboarding/cv_import (PROCESS Entry 49)
# ---------------------------------------------------------------------------

# 5 MB max — well above any realistic CV size, low enough that a
# malicious user can't OOM the process via large multipart uploads.
_MAX_CV_BYTES = 5 * 1024 * 1024


@router.post("/onboarding/cv_import")
async def cv_import(
    file: UploadFile = File(...),
    _user_id: str = Depends(get_current_user_id),
) -> dict:
    """Extract structured data from an uploaded CV (PDF / DOCX / TXT).

    Single DeepSeek V4 Flash call (~5s) — returns the full CVImport shape with
    name, location, contact email, role rows + bullets, education,
    projects, skills, professional_summary, and the chronological
    narrative bio.

    Stateless — no session or profile is written here; the wizard's
    localStorage draft holds the result until the user clicks Finish.
    """
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_file"},
        )
    if len(data) > _MAX_CV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "file_too_large",
                "message": f"Max {_MAX_CV_BYTES // (1024 * 1024)} MB.",
            },
        )

    from ...sub_agents.cv_parser import extract_text, parse as parse_cv

    try:
        text = extract_text(data=data, filename=file.filename or "")
    except RuntimeError as exc:
        # pypdf / python-docx not installed, or extraction crashed.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "extraction_failed", "message": str(exc)[:200]},
        )

    if not text or len(text.strip()) < 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "no_text_extracted",
                "message": (
                    "Couldn't extract enough text from the file. "
                    "If it's a scanned PDF, OCR it first or paste the "
                    "text directly."
                ),
            },
        )

    try:
        out = await parse_cv(cv_text=text)
    except Exception as exc:
        log.exception("cv_parser failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "cv_parse_failed", "message": str(exc)[:200]},
        )
    return out.model_dump(mode="json")
