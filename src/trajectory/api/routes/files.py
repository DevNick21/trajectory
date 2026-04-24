"""GET /api/files/{session_id}/{filename} — serve generated files.

Two layers of defence against path traversal (MIGRATION_PLAN.md §6
risk #8):

  1. `Path(filename).name` strips any directory components, so
     `../../etc/passwd` becomes `passwd`.
  2. After resolving the final path, we verify it lives under the
     session's directory via `is_relative_to`. Catches symlink
     escapes and any other shenanigan that survived step 1.

Plus session ownership check — the demo user can only download files
from their own sessions; the same 404 for "not found" and "not yours"
prevents enumeration.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from ...config import settings
from ...storage import Storage
from ..dependencies import get_current_user_id, get_storage

router = APIRouter()
log = logging.getLogger(__name__)


_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


@router.get("/files/{session_id}/{filename}")
async def get_file(
    session_id: str,
    filename: str,
    user_id: str = Depends(get_current_user_id),
    storage: Storage = Depends(get_storage),
) -> FileResponse:
    session = await storage.get_session(session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found"},
        )

    # Layer 1: strip any directory components from the supplied name.
    safe_name = Path(filename).name
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_filename"},
        )

    session_dir = (settings.generated_dir / session_id).resolve()
    candidate = (session_dir / safe_name).resolve()

    # Layer 2: verify the resolved path is still inside session_dir.
    try:
        candidate.relative_to(session_dir)
    except ValueError:
        log.warning(
            "rejecting traversal attempt: session=%s filename=%r resolved=%s",
            session_id, filename, candidate,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_filename"},
        )

    if not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "file_not_found"},
        )

    suffix = candidate.suffix.lower()
    media_type = _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    return FileResponse(candidate, media_type=media_type, filename=safe_name)
