"""Conversational onboarding flow.

9-state machine that collects career history, motivations, money,
deal-breakers, visa/location, life context, and writing samples.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel

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


class AdvanceOutcome:
    """Return value of OnboardingSession.advance().

    - `state` is the state AFTER processing the user's reply. Unchanged
      on needs_clarification / off_topic; advanced on parsed or after
      hitting the clarification cap.
    - `follow_up` is a short message to send back instead of the next
      stage's prompt: either the parser's clarification question or a
      firm off-topic redirect we synthesize here.
    - `abandon_session` is True once the user has burned too many
      off-topic attempts. Handler drops the onboarding session and
      tells them to /start over — no more LLM calls.
    """

    __slots__ = ("state", "follow_up", "abandon_session")

    def __init__(
        self,
        state: "OnboardingState",
        follow_up: Optional[str] = None,
        abandon_session: bool = False,
    ) -> None:
        self.state = state
        self.follow_up = follow_up
        self.abandon_session = abandon_session


# After this many consecutive needs_clarification replies on the same
# stage we accept whatever the user said — fall back to storing the raw
# text so downstream has SOMETHING usable rather than empty lists. Three
# gives real grace before we stop asking.
_MAX_CLARIFICATIONS_PER_STAGE = 3

# Separate (lower) budget for off_topic replies. The user is actively
# mis-using the bot rather than being vague, so we bail sooner.
_MAX_OFF_TOPIC_PER_SESSION = 3


class OnboardingSession:
    """Holds in-memory state for one user's onboarding conversation.

    Every user reply is passed through the Opus 4.7 low-effort
    onboarding parser sub-agent before we advance state. The parser
    either:
      - returns a structured parse result → we store it and move on, or
      - returns a clarification request → we bounce that follow-up back
        to the user and stay on the current stage until they answer it
        well enough.

    We keep the raw user text too for downstream audit / debugging.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.state = OnboardingState.START
        # Display name captured from Telegram's first_name / last_name on
        # /start. Populated by the bot handler, not the user. Falls back
        # to "User" during finalise if still unset.
        self.display_name: Optional[str] = None
        self.answers: dict[str, str] = {}                # raw user text per stage
        self.parsed_answers: dict[str, BaseModel] = {}   # parsed dataclass per stage
        # Consecutive needs_clarification replies on the current stage.
        self._clarification_attempts: dict[str, int] = {}
        # Cross-stage tally of off_topic replies. If this crosses the
        # session budget we abandon the onboarding.
        self._off_topic_count: int = 0

    def current_prompt(self) -> str:
        return TOPIC_PROMPTS.get(self.state.value, "")

    async def advance(self, user_text: str) -> AdvanceOutcome:
        """Parse the user's reply against the current stage's schema.

        Branches:
          - parsed → store fields, advance.
          - needs_clarification → stay on stage, return follow_up.
          - needs_clarification after cap hit → accept whatever we can
            (with raw-text fallback for list fields) and advance.
          - off_topic → stay on stage, send firm redirect. Repeated
            off_topic across the session triggers abandon_session.
        """
        from ..sub_agents.onboarding_parser import parse_stage

        current = self.state.value
        if self.state in (OnboardingState.PROCESSING, OnboardingState.DONE,
                          OnboardingState.START):
            return self._advance_unchecked()

        # Always record the raw reply so finalise_onboarding can fall
        # back to it if the parser returned empty lists.
        self.answers[current] = user_text

        try:
            result = await parse_stage(current, user_text)
        except Exception as exc:
            log.warning(
                "onboarding parser failed on stage %s — force-advancing "
                "with raw text only: %s", current, exc,
            )
            return self._advance_unchecked()

        if result is None:
            return self._advance_unchecked()

        status = getattr(result, "status", "parsed")

        # ── off_topic: user is actively misusing the bot ──────────────
        if status == "off_topic":
            self._off_topic_count += 1
            log.info(
                "onboarding: off_topic reply on %s (total=%d) — text=%r",
                current, self._off_topic_count, user_text[:80],
            )
            if self._off_topic_count >= _MAX_OFF_TOPIC_PER_SESSION:
                return AdvanceOutcome(
                    state=self.state,
                    follow_up=(
                        "I can only do onboarding right now. If you want to "
                        "try again with a fresh start, type /start."
                    ),
                    abandon_session=True,
                )
            return AdvanceOutcome(
                state=self.state,
                follow_up=(
                    "Let's stay on the onboarding question — "
                    + TOPIC_PROMPTS.get(current, "")
                ),
            )

        # ── needs_clarification: user was vague ───────────────────────
        attempts = self._clarification_attempts.get(current, 0)
        if status == "needs_clarification" and attempts < _MAX_CLARIFICATIONS_PER_STAGE:
            self._clarification_attempts[current] = attempts + 1
            base_follow_up = (
                getattr(result, "follow_up", None)
                or "Could you give me a bit more detail on that?"
            )
            # Third attempt: give the user a clear way out.
            if attempts == _MAX_CLARIFICATIONS_PER_STAGE - 1:
                base_follow_up += (
                    "  (If you'd rather skip this question, just reply "
                    "'skip' and we'll move on.)"
                )
            return AdvanceOutcome(state=self.state, follow_up=base_follow_up)

        # ── parsed, or cap hit on needs_clarification ─────────────────
        # Stash whatever structured data the parser gave us. If
        # needs_clarification-capped with empty lists, finalise will
        # backfill from the raw answer text (see finalise_onboarding).
        self.parsed_answers[current] = result
        self._clarification_attempts.pop(current, None)
        return self._advance_unchecked()

    def _advance_unchecked(self) -> AdvanceOutcome:
        idx = _STATE_SEQUENCE.index(self.state) if self.state in _STATE_SEQUENCE else -1
        if idx < len(_STATE_SEQUENCE) - 1:
            self.state = _STATE_SEQUENCE[idx + 1]
        return AdvanceOutcome(state=self.state, follow_up=None)

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
        # Samples may come in as a pre-parsed list (from the parser) or
        # as raw text still needing split. Prefer the parsed form.
        parsed_samples = self.parsed_answers.get("samples")
        if parsed_samples is not None and getattr(parsed_samples, "samples", None):
            samples = list(parsed_samples.samples)
        else:
            samples = [
                s.strip() for s in self.answers.get("samples", "").split("\n\n")
                if s.strip()
            ]
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
    """Process transcript → UserProfile + CareerEntries + WritingStyleProfile.

    Consumes `session.parsed_answers` (populated per-stage by the
    Opus 4.7 low-effort onboarding parser). Falls back to sensible
    defaults if a field is missing because the user bailed past a
    stage or the parser returned needs_clarification too many times.
    """
    from datetime import date

    from ..schemas import VisaStatus
    from ..sub_agents.style_extractor import extract as extract_style

    transcript = session.get_transcript()
    parsed = session.parsed_answers

    # ── 1. Writing style extraction (Opus 4.7 xhigh) ───────────────────
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── 2. Pull structured fields out of the parsed answers ────────────
    money = parsed.get("money")
    salary_floor = (
        getattr(money, "salary_floor_gbp", None) if money else None
    ) or 30_000
    salary_target = getattr(money, "salary_target_gbp", None) if money else None

    motivations_result = parsed.get("motivations")
    motivations = (
        list(motivations_result.motivations) if motivations_result else []
    )
    life_constraints = (
        list(motivations_result.drains) if motivations_result else []
    )
    # If the parser returned empty lists (e.g. force-advanced after
    # clarifications), keep the raw reply as a single motivation so
    # downstream generators have SOMETHING to work with.
    if not motivations and transcript.topic_answers.get("motivations"):
        motivations = [transcript.topic_answers["motivations"]]

    deal_breakers_result = parsed.get("deal_breakers")
    deal_breakers = (
        list(deal_breakers_result.deal_breakers) if deal_breakers_result else []
    )
    good_role_signals = (
        list(deal_breakers_result.good_role_signals)
        if deal_breakers_result else []
    )
    # Same fallback: if parser gave up, keep the raw reply as one item.
    if not deal_breakers and not good_role_signals and \
            transcript.topic_answers.get("deal_breakers"):
        deal_breakers = [transcript.topic_answers["deal_breakers"]]

    visa_result = parsed.get("visa")
    user_type = (
        getattr(visa_result, "user_type", None) if visa_result else None
    ) or "uk_resident"
    base_location = (
        getattr(visa_result, "base_location", None) if visa_result else None
    ) or "London"

    visa_status: Optional[VisaStatus] = None
    if user_type == "visa_holder" and visa_result is not None:
        route = visa_result.visa_route or "other"
        expiry = visa_result.visa_expiry
        if expiry is None or expiry < date.today():
            # If the user didn't give an expiry, or gave one in the past,
            # default to +2 years so downstream urgency scoring doesn't
            # treat them as already-expired.
            expiry = date(date.today().year + 2, 12, 31)
        visa_status = VisaStatus(route=route, expiry_date=expiry)

    life_result = parsed.get("life")
    current_employment = (
        getattr(life_result, "current_employment", None) if life_result else None
    ) or "EMPLOYED"
    search_duration_months = (
        getattr(life_result, "search_duration_months", None) if life_result else None
    )
    if search_duration_months and search_duration_months > 0:
        search_started_date = (
            date.today().replace(day=1) - timedelta(days=30 * search_duration_months)
        )
    else:
        search_started_date = date.today()

    user = UserProfile(
        user_id=session.user_id,
        name=session.display_name or "User",
        user_type=user_type,
        visa_status=visa_status,
        base_location=base_location,
        salary_floor=salary_floor,
        salary_target=salary_target,
        motivations=motivations,
        deal_breakers=deal_breakers,
        good_role_signals=good_role_signals,
        life_constraints=life_constraints,
        search_started_date=search_started_date,
        current_employment=current_employment,
        writing_style_profile_id=(
            style_profile.profile_id if style_profile else None
        ),
        created_at=now,
        updated_at=now,
    )

    await storage.save_user_profile(user)

    # ── 3. Seed retrievable career entries from parsed narrative + lists ─
    career_result = parsed.get("career")
    career_narrative = (
        getattr(career_result, "narrative", None) if career_result else None
    ) or transcript.topic_answers.get("career", "")
    if career_narrative:
        await storage.insert_career_entry(
            CareerEntry(
                entry_id=str(uuid.uuid4()),
                user_id=session.user_id,
                kind="conversation",
                raw_text=career_narrative,
                created_at=now,
            )
        )

    # Each motivation / deal_breaker / good_role_signal becomes its own
    # retrievable career_entry so the Phase 4 generators can cite them
    # individually.
    for motivation_text in motivations:
        await storage.insert_career_entry(
            CareerEntry(
                entry_id=str(uuid.uuid4()),
                user_id=session.user_id,
                kind="motivation",
                raw_text=motivation_text,
                created_at=now,
            )
        )
    for db_text in deal_breakers:
        await storage.insert_career_entry(
            CareerEntry(
                entry_id=str(uuid.uuid4()),
                user_id=session.user_id,
                kind="deal_breaker",
                raw_text=db_text,
                created_at=now,
            )
        )
    for signal_text in good_role_signals:
        await storage.insert_career_entry(
            CareerEntry(
                entry_id=str(uuid.uuid4()),
                user_id=session.user_id,
                kind="good_role_signal",
                raw_text=signal_text,
                created_at=now,
            )
        )

    return user
