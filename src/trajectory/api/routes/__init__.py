"""API router registration.

Each endpoint module exposes a `router: APIRouter`; this module
aggregates them into `api_router`, which `app.py` mounts. Read-only
routes land here in Wave 3, sessions/SSE in Wave 4, pack generators
in Wave 5.
"""

from __future__ import annotations

from fastapi import APIRouter

from .health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)

__all__ = ["api_router"]
