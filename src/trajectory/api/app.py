"""FastAPI application factory.

Lifespan owns the Storage singleton — initialised once on startup,
closed on shutdown. CORS is locked to `settings.web_origin` (no
wildcards, per MIGRATION_PLAN.md §6 risk #9).

Routes are registered through `routes/__init__.py::api_router` so
adding an endpoint in Wave 3+ doesn't touch this file.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..observability import (
    bind_request_id,
    install_correlation_filter,
    new_request_id,
)
from ..storage import Storage
from .routes import api_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Single Storage instance for the process lifetime.

    Both surfaces (this API + the Telegram bot) construct their own
    Storage() but talk to the same SQLite file — aiosqlite serialises
    writes. FAISS staleness across processes is a known limitation
    (MIGRATION_PLAN.md §6 risk #2, deferred for single-user demo).
    """
    install_correlation_filter()
    storage = Storage()
    await storage.initialise()
    app.state.storage = storage
    log.info("trajectory.api ready (storage initialised)")
    try:
        yield
    finally:
        await storage.close()
        log.info("trajectory.api shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Trajectory API",
        description="Web surface for the Trajectory job-search assistant.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _correlation_middleware(request: Request, call_next):
        # Honour a client-supplied X-Request-ID when present, otherwise
        # mint a new one. Propagates into every log record via the
        # contextvars-backed CorrelationFilter.
        rid = request.headers.get("x-request-id") or new_request_id()
        token = bind_request_id(rid)
        try:
            response = await call_next(request)
        finally:
            # Restore the previous value so background tasks started
            # before the request don't accidentally inherit this id.
            # contextvars.ContextVar.reset uses the token returned by
            # .set() — see trajectory.observability.bind_request_id.
            try:
                from ..observability.logging_context import _request_id_var
                _request_id_var.reset(token)
            except Exception:  # pragma: no cover — defensive
                pass
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(api_router)
    return app


# Module-level instance for `uvicorn trajectory.api.app:app`.
app = create_app()
