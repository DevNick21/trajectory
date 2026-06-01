"""Application-assist memory helpers.

This module is intentionally deterministic and cheap. The live form-filling
loop needs sub-2s nudges, so classification, rubric checks, privacy marking,
and basic memory extraction must work before any LLM call. LLM agents sit
behind this path for final polish and richer background extraction.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..schemas import (
    AdviceSnippet,
    AnswerAttempt,
    AnswerCritique,
    AnswerRubricScore,
    ApplicationAssistSession,
    ExperienceAtom,
    MemorySuggestion,
    QuestionPattern,
    QuestionType,
    StoryFrame,
    UserProfile,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def raw_retention_deadline(days: int = 30) -> datetime:
    return now_utc() + timedelta(days=days)


_SENSITIVE_PATTERNS = [
    re.compile(r"\b(?:visa|sponsor|sponsorship|right to work|graduate route)\b", re.I),
    re.compile(r"\b(?:salary|compensation|pay|offer|£\s?\d[\d,]*)\b", re.I),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b(?:\+44|0)\s?\d{3,4}\s?\d{3}\s?\d{3,4}\b"),
]


def detect_sensitive(text: str) -> bool:
    """Conservative privacy marker for hosted memory.

    Sensitive content is still saved because the product requirement is
    auto-save, but it is stored as private by default and excluded from future
    suggestions until explicitly approved.
    """

    return any(p.search(text or "") for p in _SENSITIVE_PATTERNS)


def classify_question(question_text: str, jd_text: str = "") -> QuestionPattern:
    """Map finite application-question shapes to coaching rubrics."""

    q = question_text.lower()
    ctx = f"{question_text}\n{jd_text}".lower()

    if any(w in q for w in ["right to work", "visa", "sponsor", "sponsorship"]):
        return QuestionPattern(
            question_type="visa",
            what_testing="Whether there is a legal/right-to-work blocker.",
            ideal_evidence=["clear current status", "expiry date if relevant", "sponsorship need"],
            structure_hint="Answer directly, then add the minimum supporting detail.",
            common_failures=["over-explaining immigration history", "hiding sponsorship need"],
            confidence="HIGH",
        )
    if any(w in q for w in ["salary", "compensation", "pay expectation", "expected pay"]):
        return QuestionPattern(
            question_type="salary",
            what_testing="Whether your expectations fit the employer's budget.",
            ideal_evidence=["floor", "target", "flexibility conditions"],
            structure_hint="Give a grounded range or ask for the band if the role has no data.",
            common_failures=["giving a number below your floor", "using vague market-language"],
            confidence="HIGH",
        )
    if any(w in q for w in ["why this company", "why do you want", "why are you interested"]):
        return QuestionPattern(
            question_type="motivation",
            what_testing="Whether your interest is specific rather than generic.",
            ideal_evidence=["company-specific signal", "role-specific motivation", "relevant experience"],
            structure_hint="Company signal, personal reason, concrete fit.",
            common_failures=["generic enthusiasm", "copy that would fit any employer"],
            confidence="HIGH",
        )
    if any(w in q for w in ["cover letter", "supporting statement", "personal statement"]):
        return QuestionPattern(
            question_type="cover_letter",
            what_testing="Whether you can connect the role to specific evidence from your history.",
            ideal_evidence=["opening fit", "1-2 strongest examples", "motivation"],
            structure_hint="Specific opening, evidence paragraph, close.",
            common_failures=["listing the CV", "generic company praise"],
            confidence="HIGH",
        )
    if any(w in q for w in ["value", "integrity", "inclusive", "diversity", "ethic"]):
        return QuestionPattern(
            question_type="values",
            what_testing="Whether your judgement and behaviour match the organisation's values.",
            ideal_evidence=["specific situation", "trade-off", "action", "result"],
            structure_hint="Use a compact STAR answer with the value visible in the action.",
            common_failures=["moral claims without evidence", "no trade-off"],
            confidence="MEDIUM",
        )
    if any(w in q for w in ["tell us about", "describe a time", "example of", "situation where"]):
        return QuestionPattern(
            question_type="competency",
            what_testing="Whether you have real evidence for the behaviour being assessed.",
            ideal_evidence=["situation", "task", "action", "result"],
            structure_hint="Use STAR. Spend most words on action and result.",
            common_failures=["too much background", "no measurable or observable result"],
            confidence="HIGH",
        )
    if any(
        w in ctx
        for w in [
            "python",
            "sql",
            "api",
            "architecture",
            "debug",
            "model",
            "pipeline",
            "cloud",
            "security",
            "data",
        ]
    ):
        return QuestionPattern(
            question_type="technical",
            what_testing="Whether you can show technical depth with a concrete implementation example.",
            ideal_evidence=["technical problem", "constraints", "implementation choice", "result"],
            structure_hint="Problem, trade-off, implementation, outcome.",
            common_failures=["tool list without judgement", "no trade-off", "no result"],
            confidence="MEDIUM",
        )
    if any(w in q for w in ["location", "notice", "availability", "start date"]):
        return QuestionPattern(
            question_type="screening",
            what_testing="Whether logistics fit the employer's constraints.",
            ideal_evidence=["availability", "location/remote fit", "constraints"],
            structure_hint="Answer directly and avoid extra narrative.",
            common_failures=["adding irrelevant career detail"],
            confidence="HIGH",
        )
    return QuestionPattern(
        question_type="other",
        what_testing="What evidence or fit signal the employer is trying to verify.",
        ideal_evidence=["direct answer", "specific supporting fact", "relevance to the role"],
        structure_hint="Direct answer first, then one concrete example.",
        common_failures=["generic answer", "unsupported claims"],
        confidence="LOW",
    )


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def critique_draft(
    *,
    question_text: str,
    draft_text: str,
    question_pattern: QuestionPattern,
    word_limit: Optional[int] = None,
    suggestions: Optional[list[MemorySuggestion]] = None,
    advice_snippets: Optional[list[AdviceSnippet]] = None,
) -> AnswerCritique:
    """Fast rubric critique for live nudges."""

    wc = _word_count(draft_text)
    text = draft_text.lower()
    scores: list[AnswerRubricScore] = []

    directness = 4 if wc and wc < 220 else 3 if wc else 0
    if any(x in text for x in ["i think", "maybe", "probably", "kind of"]):
        directness -= 1
    scores.append(AnswerRubricScore(
        dimension="directness",
        score=max(0, min(5, directness)),
        note="Answer starts clearly and avoids excessive hedging." if directness >= 4
        else "Lead with the answer before background detail.",
    ))

    evidence_score = 4 if any(s and s.text[:20].lower() in text for s in suggestions or []) else 2
    if any(w in text for w in ["built", "led", "owned", "improved", "reduced", "delivered"]):
        evidence_score += 1
    scores.append(AnswerRubricScore(
        dimension="evidence",
        score=max(0, min(5, evidence_score)),
        note="Uses concrete action language." if evidence_score >= 4
        else "Add a specific project, task, or responsibility.",
    ))

    has_number = bool(re.search(r"\b\d+[%x]?\b|£\s?\d", draft_text))
    scores.append(AnswerRubricScore(
        dimension="specificity",
        score=4 if has_number else 2,
        note="Specific detail is present." if has_number
        else "Add a number, scale, timeframe, or named constraint if you can.",
    ))

    has_result = any(w in text for w in ["result", "so that", "which meant", "reduced", "improved", "saved", "increased"])
    scores.append(AnswerRubricScore(
        dimension="result",
        score=4 if has_result else 1,
        note="Outcome is visible." if has_result
        else "You have the action, but not the outcome yet.",
    ))

    role_fit = 4 if question_pattern.question_type != "other" else 2
    scores.append(AnswerRubricScore(
        dimension="role_fit",
        score=role_fit,
        note=f"Answer is being shaped for a {question_pattern.question_type} prompt.",
    ))

    if word_limit is None:
        word_status = "unknown"
        word_score = 3
    elif wc > word_limit:
        word_status = "over"
        word_score = 1
    elif wc >= int(word_limit * 0.85):
        word_status = "near"
        word_score = 4
    else:
        word_status = "under"
        word_score = 4
    scores.append(AnswerRubricScore(
        dimension="word_limit",
        score=word_score,
        note="Within the word limit." if word_status != "over"
        else f"Over the {word_limit}-word limit; compress before submission.",
    ))

    scores.append(AnswerRubricScore(
        dimension="voice",
        score=3,
        note="Voice check runs during final polish against the writing profile.",
    ))

    missing: list[str] = []
    if not has_result:
        missing.append("result")
    if not has_number and question_pattern.question_type in {"technical", "competency"}:
        missing.append("specific scale or metric")
    if not draft_text.strip():
        missing.append("raw answer")

    nudge = None
    if "raw answer" in missing:
        nudge = "Give me the rough version first. A few natural sentences is enough."
    elif "result" in missing:
        nudge = "You have the action, but not the result. What changed after you did this?"
    elif "specific scale or metric" in missing:
        nudge = "Add scale if you can: users, revenue, error rate, time saved, deadline, or team size."
    elif word_status == "over":
        nudge = "This is over the limit. Keep the strongest action and result, then cut background."

    return AnswerCritique(
        question_type=question_pattern.question_type,
        what_testing=question_pattern.what_testing,
        scores=scores,
        missing_evidence=missing,
        targeted_nudge=nudge,
        word_count=wc,
        word_limit_status=word_status,
        suggested_angles=suggestions or [],
        advice_snippets=advice_snippets or [],
    )


def build_assist_session(
    *,
    user_id: str,
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    job_url: Optional[str] = None,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    jd_text: Optional[str] = None,
    private_mode: bool = False,
) -> ApplicationAssistSession:
    ts = now_utc()
    return ApplicationAssistSession(
        assist_session_id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=session_id,
        job_id=job_id,
        job_url=job_url,
        company_name=company_name,
        role_title=role_title,
        jd_text=jd_text,
        private_mode=private_mode,
        created_at=ts,
        updated_at=ts,
    )


def build_answer_attempt(
    *,
    user: UserProfile,
    question_text: str,
    question_type: QuestionType,
    raw_draft: str = "",
    transcript: Optional[str] = None,
    final_answer: Optional[str] = None,
    word_limit: Optional[int] = None,
    assist_session_id: Optional[str] = None,
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    selected_memory_ids: Optional[list[str]] = None,
    critique: Optional[AnswerCritique] = None,
    private_mode: bool = True,
) -> AnswerAttempt:
    ts = now_utc()
    combined = "\n".join([question_text, raw_draft, transcript or "", final_answer or ""])
    sensitive = detect_sensitive(combined)
    visibility = "private" if private_mode or sensitive else "normal"
    return AnswerAttempt(
        attempt_id=str(uuid.uuid4()),
        user_id=user.user_id,
        assist_session_id=assist_session_id,
        session_id=session_id,
        job_id=job_id,
        company_name=company_name,
        role_title=role_title,
        question_text=question_text,
        question_type=question_type,
        word_limit=word_limit,
        raw_draft=raw_draft,
        transcript=transcript,
        final_answer=final_answer,
        selected_memory_ids=selected_memory_ids or [],
        critique=critique,
        save_status="auto_saved",
        raw_retention_until=raw_retention_deadline(),
        sensitive=sensitive,
        visibility=visibility,
        created_at=ts,
        updated_at=ts,
    )


def deterministic_memory_from_attempt(attempt: AnswerAttempt) -> tuple[list[ExperienceAtom], list[StoryFrame]]:
    """Cheap fallback extractor used while the LLM memory job runs.

    This captures reviewable memory immediately without pretending to be
    complete. The Memory Inbox status stays pending so the user can correct
    or delete it before it influences future suggestions.
    """

    source = attempt.final_answer or attempt.raw_draft or attempt.transcript or ""
    if not source.strip():
        return [], []
    ts = now_utc()
    sensitive = attempt.sensitive or detect_sensitive(source)
    visibility = "private" if attempt.visibility == "private" or sensitive else "normal"

    atoms: list[ExperienceAtom] = []
    for atom_type, pattern in (
        ("metric", r"\b\d+[%x]?\b|£\s?\d[\d,]*"),
        ("skill", r"\b(?:python|sql|typescript|react|aws|azure|gcp|api|ml|data|etl|dashboard)\b"),
        ("result", r"\b(?:reduced|improved|saved|increased|delivered|launched|fixed)\b[^.]{0,120}"),
    ):
        for match in re.finditer(pattern, source, re.I):
            text = match.group(0).strip()
            if not text:
                continue
            atoms.append(
                ExperienceAtom(
                    atom_id=str(uuid.uuid4()),
                    user_id=attempt.user_id,
                    atom_type=atom_type,  # type: ignore[arg-type]
                    text=text[:240],
                    source_type="answer",
                    source_id=attempt.attempt_id,
                    source_excerpt=source[:500],
                    confidence=0.55,
                    sensitive=sensitive,
                    visibility=visibility,
                    review_status="pending",
                    created_at=ts,
                    updated_at=ts,
                )
            )

    title = (attempt.role_title or attempt.company_name or attempt.question_type).replace("_", " ").title()
    story = StoryFrame(
        story_id=str(uuid.uuid4()),
        user_id=attempt.user_id,
        title=f"{title} answer",
        summary=source[:700],
        angle_tags=[attempt.question_type],
        question_types=[attempt.question_type],
        atom_ids=[a.atom_id for a in atoms],
        outcome_score=0.0,
        usage_count=1,
        sensitive=sensitive,
        visibility=visibility,
        review_status="pending",
        created_at=ts,
        updated_at=ts,
    )
    return atoms, [story]


def default_advice_snippets() -> list[AdviceSnippet]:
    ts = now_utc()
    return [
        AdviceSnippet(
            advice_id="official-ncs-star-method",
            title="Use STAR for evidence questions",
            body="For behavioural or competency questions, structure the answer around situation, task, action, and result.",
            source_url="https://nationalcareers.service.gov.uk/careers-advice/interview-advice/the-star-method",
            source_type="official",
            topic_tags=["competency", "values", "technical"],
            licence_status="link-and-summary",
            citation_text="National Careers Service guidance on the STAR method.",
            created_at=ts,
        ),
        AdviceSnippet(
            advice_id="official-civil-service-behaviours",
            title="Show behaviour through evidence",
            body="Civil Service-style prompts assess behaviours through specific examples, not general claims.",
            source_url="https://www.gov.uk/government/publications/success-profiles/success-profiles-civil-service-behaviours",
            source_type="official",
            topic_tags=["competency", "values"],
            licence_status="Open Government Licence summary",
            citation_text="Civil Service Success Profiles behaviour guidance.",
            created_at=ts,
        ),
        AdviceSnippet(
            advice_id="curated-role-specific-motivation",
            title="Make motivation company-specific",
            body="A strong motivation answer links one company signal, one role signal, and one concrete piece of your history.",
            source_url="https://askpicky.com/advice/motivation-answers",
            source_type="curated",
            topic_tags=["motivation", "cover_letter"],
            licence_status="AskPicky curated",
            citation_text="AskPicky curated rubric for role-specific motivation answers.",
            created_at=ts,
        ),
    ]
