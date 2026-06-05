"""JD-first local analysis route."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...parsers import analyse_job_description
from ...parsers.jd_analysis import LocalJobAnalysis
from ..dependencies import get_current_user_id, rate_limit

router = APIRouter()


class JobAnalysisRequest(BaseModel):
    jd_text: str = Field(min_length=40, max_length=120_000)


class JobAnalysisResponse(BaseModel):
    analysis: LocalJobAnalysis


@router.post(
    "/job-analysis",
    response_model=JobAnalysisResponse,
    dependencies=[Depends(rate_limit("job_analysis"))],
)
async def analyse_job(
    req: JobAnalysisRequest,
    _user_id: str = Depends(get_current_user_id),
) -> JobAnalysisResponse:
    return JobAnalysisResponse(analysis=analyse_job_description(req.jd_text))
