"""Web onboarding endpoints (Wave 9).

Two endpoints, both stateless per ADR-003 (wizard state lives in
browser localStorage, not in the server):

  - POST /api/onboarding/parse     — helper for future per-stage UX
  - POST /api/onboarding/finalise  — write UserProfile + CareerEntries
                                      + WritingStyleProfile

The web wizard skips the LLM parser for structured stages (money,
visa, location, life, employment, name) — those are typed-form
inputs that the backend trusts. The parser still runs server-side
at finalise for the free-text voice stages (motivations,
deal-breakers, good-role-signals), matching the bot's behaviour.
If the parser returns an empty list (force-advanced past
needs_clarification), the raw text is kept as a single-item list
so Phase 4 generators have something to retrieve against.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, status

from ...config import settings
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
async def parse(req: OnboardingParseRequest) -> dict:
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


async def _parse_voice_stages(req: OnboardingFinaliseRequest) -> dict:
    """Run the parser on each non-empty voice field.

    Returns a dict of stage → parsed result (or None on parser failure
    / empty input). Parser failures don't raise — we fall back to the
    raw text wrapped as a single-item list, same pattern as the
    bot's finalise_onboarding.
    """
    from ...sub_agents.onboarding_parser import parse_stage

    async def _maybe_parse(stage: str, text: str):
        if not text.strip():
            return None
        try:
            return await parse_stage(stage, text)
        except Exception as exc:
            log.warning("onboarding parser for %s failed: %s", stage, exc)
            return None

    return {
        "motivations": await _maybe_parse("motivations", req.motivations_text),
        "deal_breakers": await _maybe_parse(
            "deal_breakers", req.deal_breakers_text,
        ),
    }


def _derive_motivations_and_drains(
    parsed, raw_text: str,
) -> tuple[list[str], list[str]]:
    motivations: list[str] = []
    drains: list[str] = []
    if parsed is not None:
        motivations = list(getattr(parsed, "motivations", []) or [])
        drains = list(getattr(parsed, "drains", []) or [])
    if not motivations and raw_text.strip():
        motivations = [raw_text.strip()]
    return motivations, drains


def _derive_deal_breakers_and_signals(
    parsed, raw_text: str, extra_signals_text: str,
) -> tuple[list[str], list[str]]:
    deal_breakers: list[str] = []
    good_role_signals: list[str] = []
    if parsed is not None:
        deal_breakers = list(getattr(parsed, "deal_breakers", []) or [])
        good_role_signals = list(
            getattr(parsed, "good_role_signals", []) or []
        )
    if not deal_breakers and not good_role_signals and raw_text.strip():
        deal_breakers = [raw_text.strip()]
    # The web wizard exposes a separate "green flags" textarea that
    # complements deal_breakers. Append any extras.
    if extra_signals_text.strip():
        good_role_signals.append(extra_signals_text.strip())
    return deal_breakers, good_role_signals


def _derive_visa_status(req: OnboardingFinaliseRequest) -> Optional[VisaStatus]:
    if req.user_type != "visa_holder":
        return None
    route = req.visa_route or "other"
    expiry = req.visa_expiry
    if expiry is None or expiry < date.today():
        # Matches bot/onboarding.py::finalise_onboarding fallback —
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
    """Write UserProfile + CareerEntries + WritingStyleProfile.

    Parsers for motivations + deal-breakers run server-side; raw
    writing samples feed the style extractor. All writes share the
    same `now` timestamp so downstream queries can correlate them.
    """
    from ...sub_agents.style_extractor import extract as extract_style

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # --- Writing style profile (Opus 4.7 xhigh — optional) -------------
    writing_style_profile_id: Optional[str] = None
    if req.writing_samples:
        try:
            profile = await extract_style(
                user_id=user_id, samples=req.writing_samples,
            )
            await storage.save_writing_style_profile(profile)
            writing_style_profile_id = profile.profile_id
        except Exception as exc:
            log.warning("style_extractor failed during finalise: %s", exc)

    # --- Voice-stage parsing --------------------------------------------
    parsed = await _parse_voice_stages(req)
    motivations, drains = _derive_motivations_and_drains(
        parsed["motivations"], req.motivations_text,
    )
    deal_breakers, good_role_signals = _derive_deal_breakers_and_signals(
        parsed["deal_breakers"], req.deal_breakers_text,
        req.good_role_signals_text,
    )

    # Web's checkbox-based life constraints append to whatever the
    # motivations parser surfaced under `drains`.
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
        writing_style_profile_id=writing_style_profile_id,
        created_at=now,
        updated_at=now,
    )
    await storage.save_user_profile(user)

    # --- Career entries --------------------------------------------------
    entries_written = 0

    if req.career_narrative.strip():
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="conversation",
            raw_text=req.career_narrative.strip(),
            created_at=now,
        ))
        entries_written += 1

    for text in motivations:
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="motivation",
            raw_text=text,
            created_at=now,
        ))
        entries_written += 1

    for text in deal_breakers:
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="deal_breaker",
            raw_text=text,
            created_at=now,
        ))
        entries_written += 1

    for text in good_role_signals:
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="good_role_signal",
            raw_text=text,
            created_at=now,
        ))
        entries_written += 1

    # Writing samples also go in as career entries so they're
    # retrievable when generators want to match the user's voice.
    for text in req.writing_samples:
        await storage.insert_career_entry(CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=user_id,
            kind="writing_sample",
            raw_text=text,
            created_at=now,
        ))
        entries_written += 1

    log.info(
        "onboarding finalised for %s: entries=%d style_profile=%s",
        user_id, entries_written,
        writing_style_profile_id or "<none>",
    )

    # Unused — but surfaces a link to settings for future /me editing.
    _ = settings.demo_user_id

    return OnboardingFinaliseResponse(
        user_id=user_id,
        writing_style_profile_id=writing_style_profile_id,
        career_entries_written=entries_written,
    )
