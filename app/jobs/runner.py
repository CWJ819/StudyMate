from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import session_scope
from app.jobs.handlers import get_handler_spec
from app.llm.base import LLMTemporaryError
from app.repositories.job_repository import (
    JOB_STATUS_FAILED,
    JOB_STATUS_RETRY_WAIT,
    JobRepository,
)

logger = logging.getLogger(__name__)


class RetryableJobError(Exception):
    def __init__(self, *, code: str, summary: str) -> None:
        self.code = code
        self.summary = summary
        super().__init__(summary)


@dataclass(frozen=True)
class JobExecutionResult:
    processed_count: int
    recovered_count: int = 0


class JobRunner:
    def __init__(self, repository: JobRepository | None = None) -> None:
        self.repository = repository or JobRepository()

    def recover_stale_jobs(self) -> int:
        with session_scope() as session:
            recovered = self.repository.recover_stale_running_jobs(
                session,
                lock_timeout_seconds=get_settings().job_lock_timeout_seconds,
            )
            session.commit()
            return recovered

    def process_available_jobs(self, *, limit: int = 10) -> JobExecutionResult:
        processed_count = 0
        for _ in range(limit):
            job_id = self._claim_next_job_id()
            if job_id is None:
                break
            self._execute_job(job_id)
            processed_count += 1
        return JobExecutionResult(processed_count=processed_count)

    def _claim_next_job_id(self) -> str | None:
        with session_scope() as session:
            job = self.repository.claim_next_available_job(session)
            return job.id if job is not None else None

    def _execute_job(self, job_id: str) -> None:
        with session_scope() as session:
            job = self.repository.get_job(session, job_id)
            if job is None or job.status != "running":
                return

            try:
                handler_spec = get_handler_spec(job.type)
                payload = handler_spec.payload_model.model_validate(job.payload_json)
                handler_spec.handler(session, payload)
                self.repository.mark_succeeded(session, job)
            except RetryableJobError as exc:
                if job.attempts < job.max_attempts:
                    delay_seconds = min(60, 2 ** max(job.attempts - 1, 0))
                    self.repository.mark_retry_wait(
                        session,
                        job,
                        error_code=exc.code,
                        error_summary=exc.summary,
                        delay_seconds=delay_seconds,
                    )
                else:
                    self.repository.mark_failed(
                        session,
                        job,
                        error_code=exc.code,
                        error_summary=exc.summary,
                    )
            except LLMTemporaryError as exc:
                if job.attempts < job.max_attempts:
                    delay_seconds = min(60, 2 ** max(job.attempts - 1, 0))
                    self.repository.mark_retry_wait(
                        session,
                        job,
                        error_code=exc.code,
                        error_summary=exc.message,
                        delay_seconds=delay_seconds,
                    )
                else:
                    self.repository.mark_failed(
                        session,
                        job,
                        error_code=exc.code,
                        error_summary=exc.message,
                    )
            except ValidationError as exc:
                self.repository.mark_failed(
                    session,
                    job,
                    error_code="JOB_PAYLOAD_INVALID",
                    error_summary=str(exc),
                )
            except AppError as exc:
                self.repository.mark_failed(
                    session,
                    job,
                    error_code=exc.code,
                    error_summary=exc.message,
                )
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.exception("Unhandled job execution error", extra={"job_id": job_id})
                self.repository.mark_failed(
                    session,
                    job,
                    error_code="JOB_EXECUTION_FAILED",
                    error_summary=str(exc),
                )

            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.exception(
                    "Failed to commit job result; marking job failed in a fresh session",
                    extra={"job_id": job_id},
                )
                self._mark_failed_after_commit_failure(job_id, exc)

    def _mark_failed_after_commit_failure(self, job_id: str, exc: Exception) -> None:
        """Write a terminal state with a brand-new session after a failed commit.

        The original session may be poisoned (PendingRollbackError / locked
        database).  A fresh session is the only reliable way to leave the job
        in a terminal state without an application restart.
        """
        try:
            with session_scope() as session:
                job = self.repository.get_job(session, job_id)
                if job is None or job.status != "running":
                    return
                self.repository.mark_failed(
                    session,
                    job,
                    error_code="JOB_EXECUTION_FAILED",
                    error_summary=f"Failed to persist job result: {type(exc).__name__}",
                )
                session.commit()
        except Exception:  # pragma: no cover - last-resort persistence failure
            logger.exception(
                "Could not mark job as failed after commit failure",
                extra={"job_id": job_id},
            )


_job_runner: JobRunner | None = None


def get_job_runner() -> JobRunner:
    global _job_runner
    if _job_runner is None:
        _job_runner = JobRunner()
    return _job_runner


async def run_worker_loop(stop_event: asyncio.Event) -> None:
    runner = get_job_runner()
    poll_interval = get_settings().job_poll_interval_seconds
    runner.recover_stale_jobs()

    while not stop_event.is_set():
        try:
            runner.recover_stale_jobs()
        except Exception:  # pragma: no cover - recovery must not kill the loop
            logger.exception("Stale job recovery failed")

        try:
            await asyncio.to_thread(runner.process_available_jobs)
        except Exception:  # pragma: no cover - safety net around loop
            logger.exception("Worker loop iteration failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            continue
