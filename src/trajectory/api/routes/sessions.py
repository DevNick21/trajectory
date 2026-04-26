"""Session API:

  - GET  /api/sessions               — slim recent-sessions list
  - GET  /api/sessions/{id}          — full detail (bundle + verdict + files)
  - POST /api/sessions/forward_job   — Phase 1 pipeline as SSE stream

All three are ownership-gated to settings.demo_user_id. The same 404
covers "not found" and "not yours" so an attacker cannot enumerate
session ids.

SSE event vocabulary (Wave 4 — see MIGRATION_PLAN.md §7):

  - {"type": "agent_complete", "agent": "<name>"}    (each Phase 1 agent finishing)
  - {"type": "verdict", "data": <Verdict.model_dump>}
  - {"type": "error",   "data": {"message": "..."}}
  - {"type": "done"}                                  (sentinel from SSEEmitter.close)

`agent_started` / `agent_failed` are deliberately deferred. The
frontend infers in-progress from "agents in PHASE_1_AGENTS not yet
in completed[]"; adding explicit started/failed events would touch
every Phase 1 closure and isn't needed for the dashboard UX.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from ...config import settings
from ...progress import SSEEmitter
from ...schemas import Session, UserProfile
from ...storage import Storage
from ..dependencies import (
    get_current_user,
    get_current_user_id,
    get_storage,
    rate_limit,
)
from ..schemas import (
    CostSummary,
    ForwardJobRequest,
    GeneratedFile,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
)
from ..sse import event_stream

router = APIRouter()
log = logging.getLogger(__name__)

# Strong refs to detached forward_job runners — prevents the GC from
# collecting in-flight Phase 1 / verdict tasks after the SSE client
# disconnects. Each task removes itself via add_done_callback when it
# finishes naturally, so this set is bounded by the number of
# in-flight forwards (typically 0-2 in single-user demo mode).
_RUNNING_TASKS: set = set()


_FILE_KIND_BY_SUFFIX = {
    ".docx": "docx",
    ".pdf": "pdf",  # may be reclassified to latex_pdf below
}


def _classify_file(filename: str) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == ".pdf" and filename.startswith("cv_latex_"):
        return "latex_pdf"
    return _FILE_KIND_BY_SUFFIX.get(suffix, "other")


def _list_generated_files(session_id: str) -> list[GeneratedFile]:
    """Scan `data/generated/{session_id}/` for renderer output.

    Returns an empty list when the directory doesn't exist (no pack
    has been generated yet) — never raises.
    """
    session_dir = settings.generated_dir / session_id
    if not session_dir.is_dir():
        return []
    out: list[GeneratedFile] = []
    for entry in sorted(session_dir.iterdir()):
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        out.append(
            GeneratedFile(
                filename=entry.name,
                size_bytes=size,
                kind=_classify_file(entry.name),
                download_url=f"/api/files/{session_id}/{entry.name}",
            )
        )
    return out


def _summarise(session: Session) -> SessionSummary:
    bundle: Optional[dict[str, Any]] = session.phase1_output
    role_title = None
    company_name = None
    if isinstance(bundle, dict):
        jd = bundle.get("extracted_jd") or {}
        cr = bundle.get("company_research") or {}
        if isinstance(jd, dict):
            role_title = jd.get("role_title")
        if isinstance(cr, dict):
            company_name = cr.get("company_name")

    verdict_decision: Optional[str] = None
    if session.verdict is not None:
        # session.verdict is either a Verdict instance (fresh from
        # storage helpers) or a raw dict (older code paths). Tolerate
        # both — the response model accepts only the decision string.
        decision_attr = getattr(session.verdict, "decision", None)
        if decision_attr is None and isinstance(session.verdict, dict):
            decision_attr = session.verdict.get("decision")
        if decision_attr in ("GO", "NO_GO"):
            verdict_decision = decision_attr

    return SessionSummary(
        id=session.session_id,
        job_url=session.job_url,
        intent=session.intent,
        created_at=session.created_at,
        verdict=verdict_decision,
        role_title=role_title,
        company_name=company_name,
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> SessionListResponse:
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 100",
        )
    sessions = await storage.get_recent_sessions(user_id=user_id, limit=limit)
    return SessionListResponse(sessions=[_summarise(s) for s in sessions])


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> SessionDetailResponse:
    session = await storage.get_session(session_id)
    if session is None or session.user_id != user_id:
        # Don't distinguish "not found" from "not yours" — same 404
        # so an attacker can't enumerate session IDs.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found"},
        )

    cost = await storage.session_cost_summary(session_id)

    verdict_payload: Optional[dict[str, Any]] = None
    if session.verdict is not None:
        verdict_payload = (
            session.verdict.model_dump(mode="json")
            if hasattr(session.verdict, "model_dump")
            else session.verdict
        )

    return SessionDetailResponse(
        id=session.session_id,
        user_id=session.user_id,
        job_url=session.job_url,
        intent=session.intent,
        created_at=session.created_at,
        research_bundle=session.phase1_output,
        verdict=verdict_payload,
        generated_files=_list_generated_files(session_id),
        cost_summary=CostSummary(**cost),
    )


# ---------------------------------------------------------------------------
# POST /api/sessions/forward_job — Phase 1 pipeline as SSE stream
# ---------------------------------------------------------------------------


def _new_session(user_id: str, job_url: str) -> Session:
    return Session(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        intent="forward_job",
        job_url=job_url,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


async def _run_forward_job(
    *,
    job_url: str,
    user: UserProfile,
    session: Session,
    storage: Storage,
    queue: asyncio.Queue,
    emitter: SSEEmitter,
) -> None:
    """Background runner. Pushes events to the queue via the emitter,
    then the verdict event on success or an error event on failure,
    then closes the emitter (which enqueues the `done` sentinel).
    """
    # Lazy import — avoids pulling the orchestrator graph into the
    # FastAPI startup path for routes that don't need it.
    from ...orchestrator import handle_forward_job

    try:
        await storage.save_session(session)
        bundle, verdict = await handle_forward_job(
            job_url=job_url,
            user=user,
            session=session,
            storage=storage,
            emitter=emitter,
        )
        await queue.put({
            "type": "verdict",
            "data": verdict.model_dump(mode="json"),
        })
    except asyncio.CancelledError:
        # Client disconnected — let the cancellation propagate so
        # the runner task exits cleanly. Don't enqueue a final event;
        # the consumer is gone.
        raise
    except Exception:
        log.exception("forward_job failed for %s", job_url)
        await queue.put({
            "type": "error",
            "data": {"message": "Research failed. Try the URL again, or paste it directly."},
        })
    finally:
        await emitter.close()


@router.post(
    "/sessions/forward_job",
    dependencies=[Depends(rate_limit("forward_job"))],
)
async def forward_job(
    req: ForwardJobRequest,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> EventSourceResponse:
    """Run Phase 1 + verdict, streaming progress to the client.

    Returns an SSE stream. The runner task is cancelled if the client
    disconnects mid-pipeline (MIGRATION_PLAN.md §6 risk #10).
    """
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)
    session = _new_session(user.user_id, str(req.job_url))

    runner_task = asyncio.create_task(
        _run_forward_job(
            job_url=str(req.job_url),
            user=user,
            session=session,
            storage=storage,
            queue=queue,
            emitter=emitter,
        )
    )

    async def stream():
        try:
            async for frame in event_stream(queue):
                yield frame
        finally:
            # Client disconnected (changed tabs, navigated away, or
            # closed the page) — DO NOT cancel the runner. Let Phase 1
            # + verdict finish in the background so the session page
            # has data when the user comes back.
            #
            # Trade-off: an aborted SSE leaves an orphan task running
            # to completion. Acceptable for single-user demo; in
            # multi-user prod we'd want a per-user task registry with
            # deduplication. For now the runner saves bundle + verdict
            # to SQLite; the next /api/sessions/{id} hit returns them.
            if not runner_task.done():
                # Detach: if the request is shutting down, the task
                # will continue under the application loop until it
                # returns naturally.
                _RUNNING_TASKS.add(runner_task)
                runner_task.add_done_callback(_RUNNING_TASKS.discard)

    return EventSourceResponse(stream())
