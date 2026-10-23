from fastapi import APIRouter

from app.db.session import session_scope
from app.schemas.job import JobResponse, LLMCallSummaryResponse
from app.services.job_service import JobService

router = APIRouter(tags=["jobs"])
service = JobService()


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    with session_scope() as session:
        return service.get_job(session, job_id)


@router.get("/jobs/{job_id}/llm-calls", response_model=LLMCallSummaryResponse)
async def get_job_llm_calls(job_id: str) -> LLMCallSummaryResponse:
    with session_scope() as session:
        return service.get_llm_call_summary(session, job_id)
