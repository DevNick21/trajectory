"""Batch queue API (#5 in the money-no-object roadmap).

Four endpoints under /api/queue:

  - POST   /api/queue            — add one URL or a list
  - GET    /api/queue            — list queued items (+ status counters)
  - DELETE /api/queue/{id}       — remove a queued item
  - POST   /api/queue/process    — SSE stream; runs Phase 1 for every
                                    pending item with a bounded
                                    asyncio.Semaphore (default 3)

The batch runner reuses `orchestrator.handle_forward_job` unchanged.
Each queued job becomes a real `Session` when processed; failures
keep the queue entry with `status="failed"` + an `error` blurb so the
user can retry or delete from the web UI.

Concurrency cap defaults to 3 — high enough to feel parallel, low
enough to stay inside provider rate limits for the demo budget.
Bumped via the `QUEUE_BATCH_CONCURRENCY` env var if needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sse_starlette.sse import EventSourceResponse

from ...config import settings
from ...progress import SSEEmitter
from ...schemas import QueuedJob, Session, UserProfile
from ...storage import Storage
from ..dependencies import get_current_user, get_storage, rate_limit
from ..schemas import (
    QueueAddRequest,
    QueueItem,
    QueueListResponse,
)
from ..sse import event_stream

router = APIRouter()
log = logging.getLogger(__name__)


def _default_concurrency() -> int:
    try:
        return max(1, min(int(os.environ.get("QUEUE_BATCH_CONCURRENCY", "3")), 10))
    except ValueError:
        return 3


# ---------------------------------------------------------------------------
# POST /api/queue
# ---------------------------------------------------------------------------


@router.post(
    "/queue",
    response_model=list[QueueItem],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("chitchat"))],
)
async def add_to_queue(
    req: QueueAddRequest,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> list[QueueItem]:
    urls: list[str] = []
    if req.job_url:
        urls.append(str(req.job_url))
    if req.job_urls:
        urls.extend(str(u) for u in req.job_urls)
    # De-dupe on insert — a user pasting the same URL twice in one
    # batch doesn't want duplicate queue rows.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    if not deduped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "empty_payload", "message": "job_url or job_urls required"},
        )

    inserted: list[QueueItem] = []
    for u in deduped:
        job = await storage.insert_queued_job(user_id=user.user_id, job_url=u)
        inserted.append(_to_item(job))
    return inserted


# ---------------------------------------------------------------------------
# GET /api/queue
# ---------------------------------------------------------------------------


def _to_item(job: QueuedJob) -> QueueItem:
    return QueueItem(
        id=job.id,
        job_url=job.job_url,
        status=job.status,
        session_id=job.session_id,
        error=job.error,
        added_at=job.added_at,
        processed_at=job.processed_at,
    )


@router.get("/queue", response_model=QueueListResponse)
async def list_queue(
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> QueueListResponse:
    jobs = await storage.list_queued_jobs(user_id=user.user_id)
    items = [_to_item(j) for j in jobs]
    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    return QueueListResponse(
        items=items,
        pending_count=counts["pending"],
        processing_count=counts["processing"],
        done_count=counts["done"],
        failed_count=counts["failed"],
    )


# ---------------------------------------------------------------------------
# DELETE /api/queue/{id}
# ---------------------------------------------------------------------------


@router.delete("/queue/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_queue(
    job_id: str,
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> Response:
    deleted = await storage.remove_queued_job(job_id=job_id, user_id=user.user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "queued_job_not_found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# POST /api/queue/process — SSE batch runner
# ---------------------------------------------------------------------------


def _new_session(user_id: str, job_url: str) -> Session:
    return Session(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        intent="forward_job",
        job_url=job_url,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


class _PersistingEmitter:
    """Wraps an emitter so every emitted event is also persisted to
    session_progress_events. Persistence failures are logged but never
    block the live stream."""

    def __init__(self, inner, storage: Storage, session_id: str) -> None:
        self._inner = inner
        self._storage = storage
        self._session_id = session_id

    async def emit(self, event: dict) -> None:
        try:
            await self._storage.append_session_progress_event(
                self._session_id, event,
            )
        except Exception:
            log.exception(
                "Failed to persist progress event for session %s",
                self._session_id,
            )
        await self._inner.emit(event)

    async def close(self) -> None:
        await self._inner.close()


async def _process_one(
    job: QueuedJob,
    user: UserProfile,
    storage: Storage,
    queue: asyncio.Queue,
    sem: asyncio.Semaphore,
) -> None:
    """Run Phase 1 + verdict for a single queue entry.

    Emits `started` → `completed` (or `failed`) events on the shared
    output queue. Per-agent progress events are persisted via a
    _PersistingEmitter so session detail pages can show progress
    history for queue-created sessions too.
    """
    async with sem:
        await queue.put({
            "type": "started",
            "id": job.id,
            "job_url": job.job_url,
        })
        await storage.mark_queued_job_processing(job.id)
        try:
            from ...orchestrator import handle_forward_job
            from ...progress.emitter import NoOpEmitter

            session = _new_session(user.user_id, job.job_url)
            await storage.save_session(session)

            # Wrap a NoOpEmitter with persistence — the queue runner
            # doesn't stream per-agent progress live, but session
            # detail should still show the progress timeline.
            persisting = _PersistingEmitter(
                NoOpEmitter(), storage, session.session_id,
            )
            bundle, verdict = await handle_forward_job(
                job_url=job.job_url,
                user=user,
                session=session,
                storage=storage,
                emitter=persisting,
            )
            await storage.mark_queued_job_done(job.id, session.session_id)
            await queue.put({
                "type": "completed",
                "id": job.id,
                "session_id": session.session_id,
                "verdict_decision": verdict.decision,
                "verdict_headline": verdict.headline,
                "role_title": bundle.extracted_jd.role_title,
                "company_name": bundle.company_research.company_name,
            })
        except Exception as exc:
            log.exception("queue batch: job %s failed", job.id)
            await storage.mark_queued_job_failed(job.id, str(exc))
            # Sanitised — raw exception stays in the server log.
            await queue.put({
                "type": "failed",
                "id": job.id,
                "error": "Research failed. Re-run individually for details.",
            })


async def _run_batch_via_api(
    user: UserProfile,
    storage: Storage,
    queue: asyncio.Queue,
    emitter: SSEEmitter,
    pending: list[QueuedJob],
) -> None:
    """Batch queue processing path.

    Processes pending jobs concurrently with a semaphore for load control.
    """
    log.info(
        "Batch runner: %d pending jobs. Running in-process with concurrency %d.",
        len(pending), _default_concurrency(),
    )

    sem = asyncio.Semaphore(_default_concurrency())
    await asyncio.gather(
        *[_process_one(j, user, storage, queue, sem) for j in pending],
        return_exceptions=False,
    )


async def _run_batch(
    user: UserProfile,
    storage: Storage,
    queue: asyncio.Queue,
    emitter: SSEEmitter,
    pending: list[QueuedJob] | None = None,
) -> None:
    try:
        if pending is None:
            pending = await storage.list_queued_jobs(
                user_id=user.user_id,
                status_filter="pending",
            )
        if not pending:
            await queue.put({
                "type": "done",
                "processed_count": 0,
                "note": "no pending jobs in queue",
            })
            return

        if settings.enable_batch_queue_runner:
            await _run_batch_via_api(user, storage, queue, emitter, pending)
        else:
            sem = asyncio.Semaphore(_default_concurrency())
            await asyncio.gather(
                *[_process_one(j, user, storage, queue, sem) for j in pending],
                return_exceptions=False,
            )
        await queue.put({
            "type": "done",
            "processed_count": len(pending),
        })
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("queue batch: gather raised unexpectedly")
        await queue.put({
            "type": "error",
            "data": {"message": "Batch processing failed."},
        })
    finally:
        await emitter.close()


@router.post("/queue/process")
async def process_queue(
    user: UserProfile = Depends(get_current_user),
    storage: Storage = Depends(get_storage),
) -> EventSourceResponse:
    """Run every pending queue item in parallel, streaming per-job
    started/completed/failed events. Up to 3 concurrent Phase 1
    pipelines by default (tunable via QUEUE_BATCH_CONCURRENCY)."""
    pending = await storage.list_queued_jobs(
        user_id=user.user_id,
        status_filter="pending",
    )
    queue: asyncio.Queue = asyncio.Queue()
    emitter = SSEEmitter(queue)

    runner_task = asyncio.create_task(
        _run_batch(user, storage, queue, emitter, pending)
    )

    async def stream() -> AsyncIterator[dict]:
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

    from ..sse import SSE_HEADERS
    return EventSourceResponse(stream(), headers=SSE_HEADERS)
