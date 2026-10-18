from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from app.db.session import session_scope
from app.jobs.handlers import HANDLERS, JobHandlerSpec
from app.jobs.runner import JobRunner, RetryableJobError
from app.repositories.job_repository import JobRepository


class PayloadModel(BaseModel):
    value: str


def test_job_runner_retries_and_then_succeeds(migrated_database_url: str) -> None:
    attempts = {"count": 0}

    def flaky_handler(session, payload: PayloadModel) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RetryableJobError(code="TEMPORARY_FAILURE", summary="Try again")

    HANDLERS["test.flaky"] = JobHandlerSpec(payload_model=PayloadModel, handler=flaky_handler)
    repository = JobRepository()
    runner = JobRunner(repository=repository)

    try:
        with session_scope() as session:
            job = repository.create_job(
                session,
                job_type="test.flaky",
                payload_json={"value": "ok"},
                max_attempts=2,
            )
            session.commit()
            job_id = job.id

        runner.process_available_jobs()

        with session_scope() as session:
            first_job = repository.get_job(session, job_id)
            assert first_job is not None
            assert first_job.status == "retry_wait"
            first_job.run_after = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()

        runner.process_available_jobs()

        with session_scope() as session:
            final_job = repository.get_job(session, job_id)
            assert final_job is not None
            assert final_job.status == "succeeded"
            assert final_job.attempts == 2
    finally:
        HANDLERS.pop("test.flaky", None)


def test_job_runner_fails_after_max_attempts(migrated_database_url: str) -> None:
    def always_retry(session, payload: PayloadModel) -> None:
        raise RetryableJobError(code="TEMPORARY_FAILURE", summary="still broken")

    HANDLERS["test.always_retry"] = JobHandlerSpec(
        payload_model=PayloadModel,
        handler=always_retry,
    )
    repository = JobRepository()
    runner = JobRunner(repository=repository)

    try:
        with session_scope() as session:
            job = repository.create_job(
                session,
                job_type="test.always_retry",
                payload_json={"value": "x"},
                max_attempts=1,
            )
            session.commit()
            job_id = job.id

        runner.process_available_jobs()

        with session_scope() as session:
            failed_job = repository.get_job(session, job_id)
            assert failed_job is not None
            assert failed_job.status == "failed"
            assert failed_job.error_code == "TEMPORARY_FAILURE"
    finally:
        HANDLERS.pop("test.always_retry", None)


def test_job_runner_recovers_stale_running_jobs(migrated_database_url: str) -> None:
    handled = {"count": 0}

    def success_handler(session, payload: PayloadModel) -> None:
        handled["count"] += 1

    HANDLERS["test.recover"] = JobHandlerSpec(
        payload_model=PayloadModel,
        handler=success_handler,
    )
    repository = JobRepository()
    runner = JobRunner(repository=repository)

    try:
        with session_scope() as session:
            job = repository.create_job(
                session,
                job_type="test.recover",
                payload_json={"value": "y"},
                max_attempts=2,
            )
            session.commit()
            job_id = job.id

        with session_scope() as session:
            claimed_job = repository.claim_next_available_job(session)
            assert claimed_job is not None
            claimed_job.locked_at = datetime.now(UTC) - timedelta(hours=1)
            session.commit()

        recovered = runner.recover_stale_jobs()
        assert recovered == 1
        runner.process_available_jobs()

        with session_scope() as session:
            final_job = repository.get_job(session, job_id)
            assert final_job is not None
            assert final_job.status == "succeeded"
            assert handled["count"] == 1
    finally:
        HANDLERS.pop("test.recover", None)
