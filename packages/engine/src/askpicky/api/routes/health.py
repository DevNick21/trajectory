"""GET /health — liveness probe.

Returns enough metadata to confirm the lifespan ran (storage attached).
Does NOT touch user data — kept cheap so smoke tests + frontend boot
checks can hit it freely.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...storage import Storage
from ..dependencies import get_storage

router = APIRouter()


@router.get("/health")
async def health(storage: Storage = Depends(get_storage)) -> dict:
    return {
        "status": "ok",
        "service": "askpicky.api",
        "version": "0.1.0",
        "storage_initialised": storage is not None,
    }


@router.get("/api/version")
async def api_version() -> dict:
    return {
        "service": "askpicky.api",
        "version": "0.1.0",
    }
