"""GET /api/sessions and GET /api/sessions/{id} — read-only session API.

Both endpoints enforce ownership: the demo user can only see their
own sessions. List returns slim summaries; detail returns the full
research bundle, verdict, generated files, and cost breakdown.

Wave 4 will add `POST /api/sessions/forward_job` (SSE).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from ...config import settings
from ...schemas import Session
from ...storage import Storage
from ..dependencies import get_current_user_id, get_storage
from ..schemas import (
    CostSummary,
    GeneratedFile,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
)

router = APIRouter()
log = logging.getLogger(__name__)


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
