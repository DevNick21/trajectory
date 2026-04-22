"""Conversational onboarding flow.

9-state machine that collects career history, motivations, money,
deal-breakers, visa/location, life context, and writing samples.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from ..schemas import CareerEntry, OnboardingTranscript, UserProfile

log = logging.getLogger(__name__)

TOPIC_PROMPTS: dict[str, str] = {
    "career": (
        "Let's start with your career story. Give me the quick version — "
        "roles you've held, what you built or shipped, and what you're most "
        "proud of. Don't worry about formatting, just talk."
    ),
    "motivations": (
        "What energises you at work? And what drains you? Be specific — "
        "'interesting problems' is too vague. What does an actually good day look like?"
    ),
    "money": (
        "What's your salary floor — the number below which you wouldn't accept? "
        "And what are you targeting? UK pounds, annual gross."
    ),
    "deal_breakers": (
        "What are your hard nos? Industries, work patterns, management styles, "
        "location constraints, anything. Also — what are the green flags that make "
        "you think 'yes, I want this'?"
    ),
    "visa": (
        "Tell me your situation: UK resident or on a visa? If visa, which route "
        "and when does it expire? Where are you based and are you open to relocating?"
    ),
    "life": (
        "Last one: what's your situation right now? Employed, notice period, or "
        "searching full-time? How long have you been looking? Any hard deadlines?"
    ),
    "samples": (
        "Finally — paste 2-3 samples of your professional writing. Emails, "
        "cover letters, LinkedIn messages, Slack messages. Anything you wrote "
        "that sounds like you. I'll use these to match your voice in generated output."
    ),
    "confirm": (
        "Got it. Let me process everything and set up your profile — "
        "this takes a moment."
    ),
}


class OnboardingState(str, Enum):
    START = "start"
    CAREER = "career"
    MOTIVATIONS = "motivations"
    MONEY = "money"
    DEAL_BREAKERS = "deal_breakers"
    VISA = "visa"
    LIFE = "life"
    SAMPLES = "samples"
    PROCESSING = "processing"
    DONE = "done"


_STATE_SEQUENCE = [
    OnboardingState.CAREER,
    OnboardingState.MOTIVATIONS,
    OnboardingState.MONEY,
    OnboardingState.DEAL_BREAKERS,
    OnboardingState.VISA,
    OnboardingState.LIFE,
    OnboardingState.SAMPLES,
    OnboardingState.PROCESSING,
    OnboardingState.DONE,
]


class OnboardingSession:
    """Holds in-memory state for one user's onboarding conversation."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.state = OnboardingState.START
        self.answers: dict[str, str] = {}

    def current_prompt(self) -> str:
        return TOPIC_PROMPTS.get(self.state.value, "")

    def advance(self, user_text: str) -> OnboardingState:
        """Store the user's answer and move to the next state."""
        if self.state not in (OnboardingState.PROCESSING, OnboardingState.DONE):
            self.answers[self.state.value] = user_text

        idx = _STATE_SEQUENCE.index(self.state) if self.state in _STATE_SEQUENCE else -1
        if idx < len(_STATE_SEQUENCE) - 1:
            self.state = _STATE_SEQUENCE[idx + 1]
        return self.state

    def is_done(self) -> bool:
        return self.state == OnboardingState.DONE

    def is_collecting(self) -> bool:
        return self.state not in (
            OnboardingState.START,
            OnboardingState.PROCESSING,
            OnboardingState.DONE,
        )

    def next_prompt(self) -> Optional[str]:
        """Return the prompt for the current state, or None if done/processing."""
        if self.state in (OnboardingState.PROCESSING, OnboardingState.DONE):
            return None
        return TOPIC_PROMPTS.get(self.state.value)

    def get_transcript(self) -> OnboardingTranscript:
        samples = [s.strip() for s in self.answers.get("samples", "").split("\n\n") if s.strip()]
        topic_answers = {k: v for k, v in self.answers.items() if k != "samples"}
        return OnboardingTranscript(
            user_id=self.user_id,
            topic_answers=topic_answers,
            writing_samples=samples,
        )


async def finalise_onboarding(
    session: OnboardingSession,
    storage,
) -> UserProfile:
    """Process transcript → UserProfile + CareerEntries + WritingStyleProfile."""
    from ..sub_agents.style_extractor import extract as extract_style
    from ..sub_agents import style_extractor

    transcript = session.get_transcript()

    # Extract writing style from samples
    style_profile = None
    if transcript.writing_samples:
        try:
            style_profile = await extract_style(
                user_id=session.user_id,
                samples=transcript.writing_samples,
            )
            await storage.save_writing_style_profile(style_profile)
        except Exception as exc:
            log.warning("Style extraction failed: %s", exc)

    # Build a minimal UserProfile from transcript answers
    now = datetime.utcnow()
    from ..schemas import VisaStatus
    from datetime import date

    visa_text = transcript.topic_answers.get("visa", "")
    money_text = transcript.topic_answers.get("money", "")
    life_text = transcript.topic_answers.get("life", "")

    # Parse salary floor from money answer (best-effort)
    import re
    salary_floor = 30000
    salary_target = None
    numbers = re.findall(r"£?(\d[\d,]+)", money_text)
    if numbers:
        vals = [int(n.replace(",", "")) for n in numbers]
        salary_floor = vals[0] if vals else 30000
        salary_target = vals[1] if len(vals) > 1 else None

    # Determine user_type
    user_type = "uk_resident"
    visa_status = None
    if any(kw in visa_text.lower() for kw in ["visa", "graduate", "skilled", "student"]):
        user_type = "visa_holder"
        # Best-effort expiry parse
        expiry_match = re.search(r"(\d{4})", visa_text)
        expiry_year = int(expiry_match.group(1)) if expiry_match else date.today().year + 2
        from datetime import date as d_date
        visa_status = VisaStatus(route="graduate", expiry_date=d_date(expiry_year, 12, 31))

    # Employment status
    employment = "EMPLOYED"
    if any(kw in life_text.lower() for kw in ["unemployed", "searching", "not working"]):
        employment = "UNEMPLOYED"
    elif "notice" in life_text.lower():
        employment = "NOTICE_PERIOD"

    # Location — default to London
    location_match = re.search(r"\b(London|Manchester|Edinburgh|Bristol|Birmingham|Leeds|Glasgow|Cambridge|Oxford)\b", visa_text, re.I)
    location = location_match.group(0) if location_match else "London"

    # Motivations and deal-breakers from text
    motivations_raw = transcript.topic_answers.get("motivations", "")
    deal_breakers_raw = transcript.topic_answers.get("deal_breakers", "")
    motivations = [motivations_raw] if motivations_raw else []
    deal_breakers = [deal_breakers_raw] if deal_breakers_raw else []

    user = UserProfile(
        user_id=session.user_id,
        name="User",  # updated after profile save
        user_type=user_type,
        visa_status=visa_status,
        base_location=location,
        salary_floor=salary_floor,
        salary_target=salary_target,
        motivations=motivations,
        deal_breakers=deal_breakers,
        good_role_signals=[],
        life_constraints=[],
        search_started_date=date.today(),
        current_employment=employment,
        writing_style_profile_id=style_profile.profile_id if style_profile else None,
        created_at=now,
        updated_at=now,
    )

    await storage.save_user_profile(user)

    # Seed career entries from career narrative
    career_text = transcript.topic_answers.get("career", "")
    if career_text:
        entry = CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=session.user_id,
            kind="conversation",
            raw_text=career_text,
            created_at=now,
        )
        await storage.insert_career_entry(entry)

    for motivation_text in motivations:
        entry = CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=session.user_id,
            kind="motivation",
            raw_text=motivation_text,
            created_at=now,
        )
        await storage.insert_career_entry(entry)

    for db_text in deal_breakers:
        entry = CareerEntry(
            entry_id=str(uuid.uuid4()),
            user_id=session.user_id,
            kind="deal_breaker",
            raw_text=db_text,
            created_at=now,
        )
        await storage.insert_career_entry(entry)

    return user
