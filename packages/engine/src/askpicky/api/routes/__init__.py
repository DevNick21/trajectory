"""API router registration.

Each endpoint module exposes a `router: APIRouter`; this module
aggregates them into `api_router`, which `app.py` mounts. Convention:
infrastructure (health) at root, everything else under `/api`.
"""

from __future__ import annotations

from fastapi import APIRouter

from .applications import router as applications_router
from .assist import router as assist_router
from .career import router as career_router
from .chat import router as chat_router
from .files import router as files_router
from .health import router as health_router
from .job_analysis import router as job_analysis_router
from .onboarding import router as onboarding_router
from .outcomes import router as outcomes_router
from .pack import router as pack_router
from .profile import router as profile_router
from .privacy import router as privacy_router
from .queue import router as queue_router
from .sessions import router as sessions_router

api_router = APIRouter()

# Infrastructure: liveness probe at root for cheap monitoring.
api_router.include_router(health_router)

# Web app endpoints under /api so the Vite proxy + future deployment
# can route everything to a single mount point.
api_router.include_router(profile_router, prefix="/api")
api_router.include_router(onboarding_router, prefix="/api")
api_router.include_router(sessions_router, prefix="/api")
api_router.include_router(pack_router, prefix="/api")
api_router.include_router(queue_router, prefix="/api")
api_router.include_router(job_analysis_router, prefix="/api")
api_router.include_router(files_router, prefix="/api")
api_router.include_router(career_router, prefix="/api")
api_router.include_router(chat_router, prefix="/api")
api_router.include_router(outcomes_router, prefix="/api")
api_router.include_router(applications_router, prefix="/api")
api_router.include_router(assist_router, prefix="/api")
api_router.include_router(privacy_router, prefix="/api")

__all__ = ["api_router"]
