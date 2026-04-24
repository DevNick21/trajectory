"""GET /health — liveness probe.

Returns enough metadata to confirm the lifespan ran (storage attached)
and the configured identity is wired (demo_user_id non-empty). Does
NOT touch the database — kept cheap so smoke tests + frontend boot
checks can hit it freely.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config import settings
from ...storage import Storage
from ..dependencies import get_storage

router = APIRouter()


@router.get("/health")
async def health(storage: Storage = Depends(get_storage)) -> dict:
    return {
        "status": "ok",
        "service": "trajectory.api",
        "version": "0.1.0",
        "storage_initialised": storage is not None,
        "demo_user_id_configured": bool(settings.demo_user_id),
    }
