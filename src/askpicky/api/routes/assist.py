"""Application assist + Memory Inbox API.

These endpoints implement the fast coaching loop:

  paste question/JD -> classify -> retrieve memories -> critique draft
  -> final polish -> approve -> memory inbox extraction.

The route keeps deterministic, sub-2s behaviour in-process. LLM polish and
optional LLM memory extraction are separate steps so users see value before
expensive/background work starts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...config import settings
from ...memory.application_assist import (
    build_answer_attempt,
    build_assist_session,
    classify_question,
    critique_draft,
    default_advice_snippets,
    deterministic_memory_from_attempt,
    now_utc,
)
from ...schemas import (
    AdviceSnippet,
    AnswerAttempt,
    AnswerCritique,
    ApplicationAnswerOutput,
    ApplicationAssistSession,
    ExperienceAtom,
    MemoryEdge,
    MemoryReviewStatus,
    MemorySuggestion,
    QuestionPattern,
    QuestionType,
    StoryFrame,
    UserProfile,
    WritingStyleProfile,
)
from ...storage import Storage
from ..dependencies import get_current_user, get_storage, rate_limit

router = APIRouter()
log = logging.getLogger(__name__)


class AssistStartRequest(BaseModel):
    session_id: Optional[str] = None
    job_id: Optional[str] = None
    job_url: Optional[str] = None
    company_name: Optional[str] = None
    role_title: Optional[str] = None
    jd_text: Optional[str] = None
    private_mode: bool = True


class AssistStartResponse(BaseModel):
    assist_session: ApplicationAssistSession


class ClassifyQuestionRequest(BaseModel):
    question_text: str = Field(min_length=1, max_length=20_000)
    jd_text: str = Field(default="", max_length=80_000)


class ClassifyQuestionResponse(BaseModel):
    pattern: QuestionPattern


class SuggestMemoryRequest(BaseModel):
    assist_session_id: Optional[str] = None
    question_text: str = Field(min_length=1, max_length=20_000)
    jd_text: str = Field(default="", max_length=80_000)
    question_type: Optional[QuestionType] = None
    k: int = Field(default=5, ge=1, le=20)
    include_private: bool = False


class SuggestMemoryResponse(BaseModel):
    pattern: QuestionPattern
    suggestions: list[MemorySuggestion]
    advice_snippets: list[AdviceSnippet]


class CritiqueDraftRequest(BaseModel):
    question_text: str = Field(min_length=1, max_length=20_000)
    raw_draft: str = Field(default="", max_length=40_000)
    transcript: Optional[str] = Field(default=None, max_length=40_000)
    word_limit: Optional[int] = Field(default=None, ge=1, le=5000)
    question_type: Optional[QuestionType] = None
    assist_session_id: Optional[str] = None
    include_private: bool = False
    selected_memory_ids: list[str] = Field(default_factory=list)


class CritiqueDraftResponse(BaseModel):
    attempt_id: str
    critique: AnswerCritique
    save_indicator: Literal["Saved privately", "Pending review", "Not saved"]


class PolishRequest(CritiqueDraftRequest):
    attempt_id: Optional[str] = None


class PolishResponse(BaseModel):
    attempt_id: str
    output: ApplicationAnswerOutput


class ApproveAnswerRequest(BaseModel):
    attempt_id: str
    final_answer: Optional[str] = Field(default=None, max_length=40_000)
    selected_memory_ids: list[str] = Field(default_factory=list)


class ApproveAnswerResponse(BaseModel):
    attempt_id: str
    memory_items_created: int
    inbox_status: Literal["pending_review"]
    save_indicator: Literal["Saved privately", "Pending review", "Not saved"]


class MemoryInboxResponse(BaseModel):
    experience_atoms: list[ExperienceAtom]
    story_frames: list[StoryFrame]


class MemoryInboxUpdateRequest(BaseModel):
    review_status: MemoryReviewStatus
    visibility: Optional[Literal["normal", "private"]] = None
    text: Optional[str] = Field(default=None, max_length=20_000)
    title: Optional[str] = Field(default=None, max_length=400)
    summary: Optional[str] = Field(default=None, max_length=20_000)
    angle_tags: Optional[list[str]] = None
    question_types: Optional[list[QuestionType]] = None


class MemoryInboxUpdateResponse(BaseModel):
    ok: bool = True


class MemoryInboxDeleteResponse(BaseModel):
    ok: bool = True


class MemoryMergeRequest(BaseModel):
    item_kind: Literal["experience_atom", "story_frame"]
    target_item_id: str
    source_item_ids: list[str] = Field(min_length=1, max_length=20)
    merged_text: Optional[str] = Field(default=None, max_length=40_000)
    title: Optional[str] = Field(default=None, max_length=400)
    visibility: Optional[Literal["normal", "private"]] = None


class MemoryMergeResponse(BaseModel):
    ok: bool = True
    merged_count: int


class MemoryExportResponse(BaseModel):
    answer_attempts: list[AnswerAttempt]
    experience_atoms: list[ExperienceAtom]
    story_frames: list[StoryFrame]


class MemoryPurgeResponse(BaseModel):
    purged_attempts: int


def _fallback_style(user_id: str) -> WritingStyleProfile:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return WritingStyleProfile(
        profile_id=f"fallback:{user_id}",
        user_id=user_id,
        tone="professional and clear",
        sentence_length_pref="medium",
        formality_level=6,
        hedging_tendency="moderate",
        signature_patterns=[],
        avoided_patterns=[],
        examples=[],
        source_sample_ids=[],
        sample_count=0,
        low_confidence_reason="no writing samples collected",
        created_at=now,
        updated_at=now,
    )


async def _ensure_advice_seeded(storage: Storage) -> None:
    # Idempotent upserts keep the advice corpus available in fresh dev DBs
    # without creating a migration dependency on external content.
    for snippet in default_advice_snippets():
        await storage.save_advice_snippet(snippet)


async def _advice_for_pattern(
    storage: Storage, pattern: QuestionPattern,
) -> list[AdviceSnippet]:
    await _ensure_advice_seeded(storage)
    snippets = await storage.list_advice_snippets(
        topic=pattern.question_type,
        limit=5,
    )
    if not snippets:
        snippets = await storage.list_advice_snippets(limit=5)
    return snippets


def _save_indicator_for_attempt(attempt: AnswerAttempt) -> Literal["Saved privately", "Pending review", "Not saved"]:
    if attempt.save_status == "not_saved":
        return "Not saved"
    if attempt.visibility == "private" or attempt.sensitive:
        return "Saved privately"
    return "Pending review"


async def _load_assist_session_owned(
    storage: Storage, assist_session_id: Optional[str], user_id: str,
) -> Optional[ApplicationAssistSession]:
    if not assist_session_id:
        return None
    session = await storage.get_application_assist_session(assist_session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "assist_session_not_found"},
        )
    return session


@router.post(
    "/assist/start",
    response_model=AssistStartResponse,
    dependencies=[Depends(rate_limit("application_assist"))],
)
async def start_assist(
    body: AssistStartRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> AssistStartResponse:
    assist_session = build_assist_session(
        user_id=user.user_id,
        session_id=body.session_id,
        job_id=body.job_id,
        job_url=body.job_url,
        company_name=body.company_name,
        role_title=body.role_title,
        jd_text=body.jd_text,
        private_mode=body.private_mode,
    )
    await storage.save_application_assist_session(assist_session)
    return AssistStartResponse(assist_session=assist_session)


@router.post(
    "/assist/classify-question",
    response_model=ClassifyQuestionResponse,
    dependencies=[Depends(rate_limit("application_assist"))],
)
async def classify_question_route(
    body: ClassifyQuestionRequest,
    _user: UserProfile = Depends(get_current_user),
) -> ClassifyQuestionResponse:
    return ClassifyQuestionResponse(
        pattern=classify_question(body.question_text, body.jd_text),
    )


@router.post(
    "/assist/suggest-memory",
    response_model=SuggestMemoryResponse,
    dependencies=[Depends(rate_limit("application_assist"))],
)
async def suggest_memory(
    body: SuggestMemoryRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> SuggestMemoryResponse:
    assist_session = await _load_assist_session_owned(
        storage, body.assist_session_id, user.user_id,
    )
    jd_text = body.jd_text or (assist_session.jd_text if assist_session else "") or ""
    pattern = (
        classify_question(body.question_text, jd_text)
        if body.question_type is None
        else classify_question(body.question_text, jd_text).model_copy(
            update={"question_type": body.question_type}
        )
    )
    suggestions = await storage.retrieve_application_memory_suggestions(
        user_id=user.user_id,
        query_text=f"{body.question_text}\n{jd_text}",
        question_type=pattern.question_type,
        k=body.k,
        include_private=body.include_private,
    )
    advice = await _advice_for_pattern(storage, pattern)
    return SuggestMemoryResponse(
        pattern=pattern,
        suggestions=suggestions,
        advice_snippets=advice,
    )


@router.post(
    "/assist/critique-draft",
    response_model=CritiqueDraftResponse,
    dependencies=[Depends(rate_limit("application_assist"))],
)
async def critique_draft_route(
    body: CritiqueDraftRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> CritiqueDraftResponse:
    assist_session = await _load_assist_session_owned(
        storage, body.assist_session_id, user.user_id,
    )
    jd_text = (assist_session.jd_text if assist_session else "") or ""
    pattern = classify_question(body.question_text, jd_text)
    if body.question_type:
        pattern = pattern.model_copy(update={"question_type": body.question_type})
    suggestions = await storage.retrieve_application_memory_suggestions(
        user_id=user.user_id,
        query_text=f"{body.question_text}\n{jd_text}",
        question_type=pattern.question_type,
        k=5,
        include_private=body.include_private,
    )
    advice = await _advice_for_pattern(storage, pattern)
    critique = critique_draft(
        question_text=body.question_text,
        draft_text=body.raw_draft or body.transcript or "",
        question_pattern=pattern,
        word_limit=body.word_limit,
        suggestions=suggestions,
        advice_snippets=advice,
    )
    attempt = build_answer_attempt(
        user=user,
        question_text=body.question_text,
        question_type=pattern.question_type,
        raw_draft=body.raw_draft,
        transcript=body.transcript,
        word_limit=body.word_limit,
        assist_session_id=body.assist_session_id,
        session_id=assist_session.session_id if assist_session else None,
        job_id=assist_session.job_id if assist_session else None,
        company_name=assist_session.company_name if assist_session else None,
        role_title=assist_session.role_title if assist_session else None,
        selected_memory_ids=body.selected_memory_ids,
        critique=critique,
        private_mode=assist_session.private_mode if assist_session else True,
    )
    await storage.save_answer_attempt(attempt)
    return CritiqueDraftResponse(
        attempt_id=attempt.attempt_id,
        critique=critique,
        save_indicator=_save_indicator_for_attempt(attempt),
    )


@router.post(
    "/assist/polish",
    response_model=PolishResponse,
    dependencies=[Depends(rate_limit("application_assist"))],
)
async def polish_answer(
    body: PolishRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> PolishResponse:
    from ...sub_agents import application_answer_shaper

    attempt: Optional[AnswerAttempt] = None
    if body.attempt_id:
        attempt = await storage.get_answer_attempt(body.attempt_id)
        if attempt is None or attempt.user_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "answer_attempt_not_found"},
            )

    assist_session = await _load_assist_session_owned(
        storage,
        body.assist_session_id or (attempt.assist_session_id if attempt else None),
        user.user_id,
    )
    jd_text = (assist_session.jd_text if assist_session else "") or ""
    pattern = classify_question(body.question_text, jd_text)
    if body.question_type:
        pattern = pattern.model_copy(update={"question_type": body.question_type})
    suggestions = await storage.retrieve_application_memory_suggestions(
        user_id=user.user_id,
        query_text=f"{body.question_text}\n{jd_text}",
        question_type=pattern.question_type,
        k=8,
        include_private=body.include_private,
    )
    advice = await _advice_for_pattern(storage, pattern)
    style = await storage.get_writing_style_profile(user.user_id) or _fallback_style(user.user_id)
    output = await application_answer_shaper.shape(
        question_text=body.question_text,
        raw_draft=body.raw_draft or (attempt.raw_draft if attempt else ""),
        transcript=body.transcript or (attempt.transcript if attempt else None),
        user=user,
        style_profile=style,
        question_pattern=pattern,
        memory_suggestions=suggestions,
        advice_snippets=advice,
        word_limit=body.word_limit,
        job_context=assist_session.model_dump(mode="json") if assist_session else {},
        private_content=bool(
            (attempt and attempt.visibility == "private")
            or (assist_session and assist_session.private_mode)
        ),
        session_id=assist_session.session_id if assist_session else None,
    )

    if attempt is None:
        attempt = build_answer_attempt(
            user=user,
            question_text=body.question_text,
            question_type=pattern.question_type,
            raw_draft=body.raw_draft,
            transcript=body.transcript,
            final_answer=output.final_answer,
            word_limit=body.word_limit,
            assist_session_id=body.assist_session_id,
            session_id=assist_session.session_id if assist_session else None,
            job_id=assist_session.job_id if assist_session else None,
            company_name=assist_session.company_name if assist_session else None,
            role_title=assist_session.role_title if assist_session else None,
            selected_memory_ids=output.memory_ids_used,
            private_mode=assist_session.private_mode if assist_session else True,
        )
    else:
        attempt.final_answer = output.final_answer
        attempt.selected_memory_ids = output.memory_ids_used or body.selected_memory_ids
        attempt.updated_at = now_utc()
    await storage.save_answer_attempt(attempt)
    output.save_indicator = _save_indicator_for_attempt(attempt)
    return PolishResponse(attempt_id=attempt.attempt_id, output=output)


async def _run_optional_memory_extractor(
    *,
    storage: Storage,
    attempt: AnswerAttempt,
) -> None:
    if not settings.enable_memory_extractor_llm:
        return
    try:
        from ...sub_agents import memory_extractor

        extracted = await memory_extractor.extract(
            attempt=attempt,
            session_id=attempt.session_id,
        )
        ts = now_utc()
        for draft in extracted.experience_atoms:
            atom = ExperienceAtom(
                atom_id=str(uuid.uuid4()),
                user_id=attempt.user_id,
                atom_type=draft.atom_type,
                text=draft.text,
                source_type="answer",
                source_id=attempt.attempt_id,
                source_excerpt=draft.source_excerpt,
                confidence=draft.confidence,
                sensitive=attempt.sensitive or draft.sensitive or extracted.sensitive_detected,
                visibility=(
                    "private"
                    if attempt.visibility == "private"
                    or attempt.sensitive
                    or draft.sensitive
                    or extracted.sensitive_detected
                    else "normal"
                ),
                review_status="pending",
                created_at=ts,
                updated_at=ts,
            )
            await storage.save_experience_atom(atom)
        for draft in extracted.story_frames:
            story = StoryFrame(
                story_id=str(uuid.uuid4()),
                user_id=attempt.user_id,
                title=draft.title,
                summary=draft.summary,
                angle_tags=draft.angle_tags,
                question_types=draft.question_types,
                atom_ids=[],
                sensitive=attempt.sensitive or draft.sensitive or extracted.sensitive_detected,
                visibility=(
                    "private"
                    if attempt.visibility == "private"
                    or attempt.sensitive
                    or draft.sensitive
                    or extracted.sensitive_detected
                    else "normal"
                ),
                review_status="pending",
                created_at=ts,
                updated_at=ts,
            )
            await storage.save_story_frame(story)
    except Exception:
        log.exception("optional memory_extractor failed for attempt=%s", attempt.attempt_id)


@router.post(
    "/assist/approve",
    response_model=ApproveAnswerResponse,
    dependencies=[Depends(rate_limit("application_assist"))],
)
async def approve_answer(
    body: ApproveAnswerRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> ApproveAnswerResponse:
    attempt = await storage.get_answer_attempt(body.attempt_id)
    if attempt is None or attempt.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "answer_attempt_not_found"},
        )
    if body.final_answer is not None:
        attempt.final_answer = body.final_answer
    attempt.selected_memory_ids = body.selected_memory_ids or attempt.selected_memory_ids
    attempt.save_status = "approved"
    attempt.updated_at = now_utc()
    await storage.save_answer_attempt(attempt)

    atoms, stories = deterministic_memory_from_attempt(attempt)
    for atom in atoms:
        await storage.save_experience_atom(atom)
    for story in stories:
        await storage.save_story_frame(story)
        for atom_id in story.atom_ids:
            await storage.save_memory_edge(
                MemoryEdge(
                    edge_id=str(uuid.uuid4()),
                    user_id=attempt.user_id,
                    source_id=atom_id,
                    target_id=story.story_id,
                    edge_type="atom_supports_story",
                    weight=1.0,
                    evidence="Deterministic extraction from approved answer.",
                    created_at=now_utc(),
                )
            )

    # Optional richer LLM extraction runs after the response path by default.
    if settings.enable_memory_extractor_llm:
        asyncio.create_task(_run_optional_memory_extractor(storage=storage, attempt=attempt))

    return ApproveAnswerResponse(
        attempt_id=attempt.attempt_id,
        memory_items_created=len(atoms) + len(stories),
        inbox_status="pending_review",
        save_indicator=_save_indicator_for_attempt(attempt),
    )


@router.get("/memory/inbox", response_model=MemoryInboxResponse)
async def memory_inbox(
    status_filter: MemoryReviewStatus = "pending",
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> MemoryInboxResponse:
    items = await storage.list_memory_inbox(user.user_id, status=status_filter)
    return MemoryInboxResponse(**items)


@router.get("/memory/export", response_model=MemoryExportResponse)
async def export_memory(
    include_raw: bool = True,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> MemoryExportResponse:
    data = await storage.export_user_memory(
        user_id=user.user_id,
        include_raw=include_raw,
    )
    await storage.append_security_audit_event(
        event_type="privacy.memory_export",
        user_id=user.user_id,
        resource_type="memory",
        payload={"include_raw": include_raw},
    )
    return MemoryExportResponse(**data)


@router.post("/memory/privacy/purge-expired", response_model=MemoryPurgeResponse)
async def purge_expired_memory_raw(
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> MemoryPurgeResponse:
    purged = await storage.purge_expired_answer_attempt_raw(user_id=user.user_id)
    await storage.append_security_audit_event(
        event_type="privacy.raw_retention_purge",
        user_id=user.user_id,
        resource_type="answer_attempts",
        payload={"purged_attempts": purged, "scheduled": False},
    )
    return MemoryPurgeResponse(purged_attempts=purged)


@router.patch(
    "/memory/inbox/{item_kind}/{item_id}",
    response_model=MemoryInboxUpdateResponse,
)
async def update_memory_inbox_item(
    item_kind: Literal["experience_atom", "story_frame"],
    item_id: str,
    body: MemoryInboxUpdateRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> MemoryInboxUpdateResponse:
    ok = await storage.update_memory_review_status(
        user_id=user.user_id,
        item_kind=item_kind,
        item_id=item_id,
        review_status=body.review_status,
        visibility=body.visibility,
        text=body.text,
        title=body.title,
        summary=body.summary,
        angle_tags=body.angle_tags,
        question_types=body.question_types,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "memory_item_not_found"},
        )
    await storage.append_security_audit_event(
        event_type="privacy.memory_review_update",
        user_id=user.user_id,
        resource_type=item_kind,
        resource_id=item_id,
        payload={
            "review_status": body.review_status,
            "visibility": body.visibility,
            "edited": any(
                value is not None
                for value in (body.text, body.title, body.summary)
            ),
        },
    )
    return MemoryInboxUpdateResponse(ok=True)


@router.delete(
    "/memory/inbox/{item_kind}/{item_id}",
    response_model=MemoryInboxDeleteResponse,
)
async def hard_delete_memory_inbox_item(
    item_kind: Literal["experience_atom", "story_frame"],
    item_id: str,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> MemoryInboxDeleteResponse:
    ok = await storage.hard_delete_memory_item(
        user_id=user.user_id,
        item_kind=item_kind,
        item_id=item_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "memory_item_not_found"},
        )
    await storage.append_security_audit_event(
        event_type="privacy.memory_hard_delete",
        user_id=user.user_id,
        resource_type=item_kind,
        resource_id=item_id,
    )
    return MemoryInboxDeleteResponse(ok=True)


@router.post("/memory/inbox/merge", response_model=MemoryMergeResponse)
async def merge_memory_inbox_items(
    body: MemoryMergeRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> MemoryMergeResponse:
    merged_count = await storage.merge_memory_items(
        user_id=user.user_id,
        item_kind=body.item_kind,
        target_item_id=body.target_item_id,
        source_item_ids=body.source_item_ids,
        merged_text=body.merged_text,
        title=body.title,
        visibility=body.visibility,
    )
    if merged_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "memory_item_not_found"},
        )
    await storage.append_security_audit_event(
        event_type="privacy.memory_merge",
        user_id=user.user_id,
        resource_type=body.item_kind,
        resource_id=body.target_item_id,
        payload={"source_count": len(body.source_item_ids), "merged_count": merged_count},
    )
    return MemoryMergeResponse(ok=True, merged_count=merged_count)
