from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.jobs.runner import get_job_runner
from app.repositories.job_repository import JobRepository
from app.schemas.job import JobResponse


class JobService:
    def __init__(self, repository: JobRepository | None = None) -> None:
        self.repository = repository or JobRepository()

    def enqueue_job(
        self,
        session: Session,
        *,
        job_type: str,
        payload_json: dict,
        max_attempts: int | None = None,
    ) -> str:
        job = self.repository.create_job(
            session,
            job_type=job_type,
            payload_json=payload_json,
            max_attempts=max_attempts or get_settings().job_max_attempts,
        )
        session.commit()
        return job.id

    def get_job(self, session: Session, job_id: str) -> JobResponse:
        job = self.repository.get_job(session, job_id)
        if job is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Job not found.",
                status_code=404,
                details={"job_id": job_id},
            )
        return JobResponse.model_validate(job)

    def trigger_processing(self) -> None:
        get_job_runner().process_available_jobs()
