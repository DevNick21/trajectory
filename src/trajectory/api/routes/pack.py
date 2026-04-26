"""Phase 4 pack generation endpoints (Wave 5).

Four individual generators:

  - POST /api/sessions/{id}/cv              → JSON, takes 10-30s
  - POST /api/sessions/{id}/cover_letter    → JSON
  - POST /api/sessions/{id}/questions       → JSON
  - POST /api/sessions/{id}/salary          → JSON

Plus the parallel runner — demo money-shot #2:

  - POST /api/sessions/{id}/full_prep       → SSE stream

The SSE stream emits per-generator events as each finishes:

  - {"type": "started",   "generator": <name>}
  - {"type": "completed", "generator": <name>, "data": {...},
                          "generated_files": [...]}
  - {"type": "failed",    "generator": <name>, "error": "..."}
  - {"type": "done"}

The four generators run via `asyncio.gather(..., return_exceptions=
True)` so a single failure can't drag the others down — each emits
its own completed/failed event independently. Partial success is the
normal case in production (e.g. CV succeeds but salary_strategist
hits a timeout); the frontend renders what arrived.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from ...progress import SSEEmitter
from ...schemas import Session, UserProfile
from ...storage import Storage
from ..dependencies import get_current_user, get_storage, rate_limit
from ..schemas import GeneratedFile, PackResult
from ..sse import event_stream
from .sessions import _list_generated_files

router = APIRouter()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_session(
    session_id: str, user: UserProfile, storage: Storage,
) -> Session:
    """Same 404 for not-found and not-yours — no enumeration."""
    session = await storage.get_session(session_id)
    if session is None or session.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found"},
        )
    return session


async def _run_cv(session: Session, user: UserProfile, storage: Storage) -> dict:
    from ...orchestrator import handle_draft_cv

    cv, *_paths = await handle_draft_cv(session, user, storage)
    return {"output": cv.model_dump(mode="json")}


async def _run_cover_letter(
    session: Session, user: UserProfile, storage: Storage,
) -> dict:
    from ...orchestrator import handle_draft_cover_letter

    cl, *_paths = await handle_draft_cover_letter(session, user, storage)
    return {"output": cl.model_dump(mode="json")}


async def _run_questions(
    session: Session, user: UserProfile, storage: Storage,
) -> dict:
    from ...orchestrator import handle_predict_questions

    lq = await handle_predict_questions(session, user, storage)
    return {"output": lq.model_dump(mode="json")}


async def _run_salary(
    session: Session, user: UserProfile, storage: Storage,
) -> dict:
    from ...orchestrator import handle_salary_advice

    sal = await handle_salary_advice(session, user, storage)
    return {"output": sal.model_dump(mode="json")}


_GENERATORS: dict[str, Callable] = {
    "cv": _run_cv,
    "cover_letter": _run_cover_letter,
    "questions": _run_questions,
    "salary": _run_salary,
}


def _generated_files(session_id: str) -> list[GeneratedFile]:
    """Re-scan the session dir after a generator runs.

    Cheaper than threading paths back through the handler return
    tuples — the file lister is the same one /api/sessions/{id} uses,
    so the contract stays consistent.
    """
    return _list_generated_files(session_id)


def _build_pack_result(
    generator: str, runner_output: dict, session_id: str,
) -> PackResult:
    return PackResult(
        generator=generator,  # type: ignore[arg-type]
        output=runner_output["output"],
        generated_files=_generated_files(session_id),
    )


# ---------------------------------------------------------------------------
# Individual generator endpoints
# ---------------------------------------------------------------------------


def _make_individual_endpoint(name: str):
    runner = _GENERATORS[name]

    async def endpoint(
        session_id: str,
        user: UserProfile = Depends(get_current_user),
        storage: Storage = Depends(get_storage),
    ) -> PackResult:
        session = await _resolve_session(session_id, user, storage)
        try:
            runner_output = await runner(session, user, storage)
        except ValueError as exc:
            # Domain precondition violation (e.g. "no research bundle —
            # forward a job first"). Surface as 409 so the frontend can
            # tell the user to forward the URL first.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "precondition_failed", "message": str(exc)},
            )
        return _build_pack_result(name, runner_output, session_id)

    endpoint.__name__ = f"{name}_endpoint"
    return endpoint


_GENERATOR_INTENT = {
    "cv": "draft_cv",
    "cover_letter": "draft_cover_letter",
    "questions": "predict_questions",
    "salary": "salary_advice",
}

router.add_api_route(
    "/sessions/{session_id}/cv",
    _make_individual_endpoint("cv"),
    methods=["POST"],
    response_model=PackResult,
    dependencies=[Depends(rate_limit(_GENERATOR_INTENT["cv"]))],
)
router.add_api_route(
    "/sessions/{session_id}/cover_letter",
    _make_individual_endpoint("cover_letter"),
    methods=["POST"],
    response_model=PackResult,
    dependencies=[Depends(rate_limit(_GENERATOR_INTENT["cover_letter"]))],
)
router.add_api_route(
    "/sessions/{session_id}/questions",
    _make_individual_endpoint("questions"),
    methods=["POST"],
    response_model=PackResult,
    dependencies=[Depends(rate_limit(_GENERATOR_INTENT["questions"]))],
)
router.add_api_route(
    "/sessions/{session_id}/salary",
    _make_individual_endpoint("salary"),
    methods=["POST"],
    response_model=PackResult,
    dependencies=[Depends(rate_limit(_GENERATOR_INTENT["salary"]))],
)


# ---------------------------------------------------------------------------
# Parallel full_prep SSE
# ---------------------------------------------------------------------------


async def _generate_one(
    name: str,
    session: Session,
    user: UserProfile,
    storage: Storage,
    queue: asyncio.Queue,
) -> None:
    """Single-generator wrapper used inside the full_prep gather.

    Emits started → completed (or failed) events through the queue
    directly — bypasses the SSEEmitter API because full_prep events
    have richer payloads than the agent_complete shape SSEEmitter is
    designed for.
    """
    runner = _GENERATORS[name]
    await queue.put({"type": "started", "generator": name})
    try:
        runner_output = await runner(session, user, storage)
    except Exception as exc:
        log.warning("full_prep generator %s failed: %r", name, exc)
        # Stripped error message — don't leak raw exception details.
        await queue.put({
            "type": "failed",
            "generator": name,
            "error": "Generator failed; try this one individually for details.",
        })
        return

    await queue.put({
        "type": "completed",
        "generator": name,
        "data": runner_output["output"],
        "generated_files": [
            f.model_dump(mode="json")
            for f in _generated_files(session.session_id)
        ],
    })


async def _run_full_prep(
    session: Session,
    user: UserProfile,
    storage: Storage,
    queue: asyncio.Queue,
    emitter: SSEEmitter,
) -> None:
    """Background runner. Fans out all four generators in parallel and
    closes the emitter when the gather completes."""
    try:
        await asyncio.gather(
            _generate_one("cv", session, user, storage, queue),
            _generate_one("cover_letter", session, user, storage, queue),
            _generate_one("questions", session, user, storage, queue),
            _generate_one("salary", session, user, storage, queue),
            return_exceptions=False,  # _generate_one catches its own errors
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Should never reach here — _generate_one catches its own errors.
        # Surface as a top-level error event for the consumer.
        log.exception("full_prep gather raised unexpectedly")
        await queue.put({
            "type": "error",
            "data": {"message": "Pack generation failed."},
        })
    finally:
        await emitter.close()  # enqueues the {"type": "done"} sentinel


@router.post(
    "/sessions/{session_id}/full_prep",
    dependencies=[Depends(rate_limit("full_prep"))],
)
async def full_prep(
    session_id: str,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> EventSourceResponse:
    session = await _resolve_session(session_id, user, storage)

    # Up-front precondition check — if there's no research bundle the
    # generators all fail identically; better to fail fast at the
    # endpoint level so the frontend gets a 409 instead of an SSE
    # stream of four `failed` events.
    if session.phase1_output is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "precondition_failed",
                "message": "Forward a job first — no research bundle on this session.",
            },
        )

    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)

    runner_task = asyncio.create_task(
        _run_full_prep(session, user, storage, queue, emitter)
    )

    async def stream():
        try:
            async for frame in event_stream(queue):
                yield frame
        finally:
            if not runner_task.done():
                runner_task.cancel()
                try:
                    await runner_task
                except (asyncio.CancelledError, Exception):
                    pass

    return EventSourceResponse(stream())


# ---------------------------------------------------------------------------
# Offer analysis (PROCESS Entry 43, Workstream F)
# ---------------------------------------------------------------------------


from fastapi import File, Form, UploadFile  # noqa: E402


@router.post(
    "/sessions/{session_id}/offer",
    dependencies=[Depends(rate_limit("salary_advice"))],
)
async def analyse_offer(
    session_id: str,
    pdf: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> dict:
    """Analyse a forwarded offer letter.

    Accepts EITHER an uploaded PDF (multipart/form-data field `pdf`) OR
    plain text (field `text`). When `session_id="none"`, runs the analysis
    without a research bundle (no market-comparison documents).
    """
    if pdf is None and not (text and text.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "missing_input", "message": "Provide a `pdf` file or `text`."},
        )

    session = None
    if session_id and session_id.lower() != "none":
        session = await storage.get_session(session_id)
        if session is None or session.user_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "session_not_found"},
            )

    pdf_bytes = await pdf.read() if pdf is not None else None

    from ...orchestrator import handle_analyse_offer
    try:
        analysis = await handle_analyse_offer(
            user=user,
            storage=storage,
            session=session,
            pdf_bytes=pdf_bytes,
            text_pasted=text or None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "bad_input", "message": str(exc)},
        )
    except Exception as exc:
        log.exception("offer analysis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "offer_analysis_failed", "message": str(exc)[:200]},
        )

    return {
        "generator": "offer",
        "output": analysis.model_dump(mode="json"),
    }
