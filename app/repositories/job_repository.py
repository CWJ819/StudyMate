from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, func, select
from sqlalchemy.orm import Session

from app.db.models.job import Job

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_RETRY_WAIT = "retry_wait"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"


class JobRepository:
    def create_job(
        self,
        session: Session,
        *,
        job_type: str,
        payload_json: dict[str, Any],
        max_attempts: int,
        run_after: datetime | None = None,
    ) -> Job:
        job = Job(
            type=job_type,
            status=JOB_STATUS_QUEUED,
            payload_json=payload_json,
            progress=0,
            attempts=0,
            max_attempts=max_attempts,
            run_after=run_after or datetime.now(UTC),
        )
        session.add(job)
        session.flush()
        session.refresh(job)
        return job

    def get_job(self, session: Session, job_id: str) -> Job | None:
        return session.get(Job, job_id)

    def claim_next_available_job(self, session: Session) -> Job | None:
        now = datetime.now(UTC)
        statement = (
            select(Job)
            .where(Job.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RETRY_WAIT]))
            .where(Job.run_after <= now)
            .order_by(Job.created_at.asc())
            .limit(1)
        )
        job = session.scalar(statement)
        if job is None:
            return None

        job.status = JOB_STATUS_RUNNING
        job.attempts += 1
        job.locked_at = now
        job.started_at = job.started_at or now
        job.finished_at = None
        job.error_code = None
        job.error_summary = None
        session.commit()
        session.refresh(job)
        return job

    def mark_succeeded(self, session: Session, job: Job) -> None:
        now = datetime.now(UTC)
        job.status = JOB_STATUS_SUCCEEDED
        job.progress = 100
        job.locked_at = None
        job.finished_at = now
        job.updated_at = now

    def update_progress(
        self,
        session: Session,
        job_id: str,
        *,
        progress: int,
        phase: str,
        completed_units: int,
        total_units: int,
        message: str | None,
    ) -> bool:
        """阶段进度写入；progress 单调不回退。调用方负责用独立短事务提交。"""
        job = session.get(Job, job_id)
        if job is None or job.status != JOB_STATUS_RUNNING:
            return False
        if progress < job.progress:
            return False
        job.progress = progress
        job.phase = phase
        job.completed_units = completed_units
        job.total_units = total_units
        job.message = message
        return True

    def mark_failed(self, session: Session, job: Job, *, error_code: str, error_summary: str) -> None:
        now = datetime.now(UTC)
        job.status = JOB_STATUS_FAILED
        job.locked_at = None
        job.finished_at = now
        job.error_code = error_code
        job.error_summary = error_summary
        job.updated_at = now

    def mark_retry_wait(
        self,
        session: Session,
        job: Job,
        *,
        error_code: str,
        error_summary: str,
        delay_seconds: int,
    ) -> None:
        now = datetime.now(UTC)
        job.status = JOB_STATUS_RETRY_WAIT
        job.locked_at = None
        job.run_after = now + timedelta(seconds=delay_seconds)
        job.error_code = error_code
        job.error_summary = error_summary
        job.updated_at = now

    def recover_stale_running_jobs(self, session: Session, *, lock_timeout_seconds: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=lock_timeout_seconds)
        jobs = list(
            session.scalars(
                select(Job)
                .where(Job.status == JOB_STATUS_RUNNING)
                .where(Job.locked_at.is_not(None))
                .where(Job.locked_at < cutoff)
            )
        )
        for job in jobs:
            job.status = JOB_STATUS_QUEUED
            job.locked_at = None
            job.error_code = None
            job.error_summary = None
        return len(jobs)

    def cancel_document_jobs(self, session: Session, *, document_id: str) -> int:
        jobs = list(
            session.scalars(
                select(Job)
                .where(Job.type == "document.parse")
                .where(Job.status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RETRY_WAIT]))
                .where(func.json_extract(Job.payload_json, "$.document_id") == document_id)
            )
        )
        now = datetime.now(UTC)
        for job in jobs:
            job.status = JOB_STATUS_CANCELLED
            job.locked_at = None
            job.finished_at = now
            job.error_code = None
            job.error_summary = "Cancelled because the source document was deleted."
        return len(jobs)
