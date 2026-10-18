from fastapi import APIRouter

from app.db.session import session_scope
from app.schemas.job import JobResponse
from app.services.job_service import JobService

router = APIRouter(tags=["jobs"])
service = JobService()


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    with session_scope() as session:
        return service.get_job(session, job_id)
