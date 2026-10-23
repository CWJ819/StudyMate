import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.core.config import reset_settings_cache
from app.core.errors import database_busy_handler
from app.db.session import session_scope
from app.llm.schemas import ShortAnswerGradingCandidate
from app.main import app
from app.repositories.job_repository import JobRepository
from app.schemas.quiz import (
    QuestionRubric,
    QuestionRubricCriterion,
    normalize_rubric,
)
from app.services.course_service import CourseService


def _create_pdf(path: Path, page_texts: list[str]) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.save(path)
    document.close()


async def _wait_for_job(client: AsyncClient, job_id: str) -> dict:
    last_body: dict | None = None
    for _ in range(80):
        response = await client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        last_body = response.json()
        if last_body["status"] in {"succeeded", "failed", "cancelled"}:
            return last_body
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {last_body}")


async def _create_course(client: AsyncClient, name: str = "Repair Test") -> str:
    response = await client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_pdf_material(client: AsyncClient, course_id: str, path: Path) -> dict:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": (path.name, handle, "application/pdf")},
        )
    assert response.status_code == 201
    body = response.json()
    job = await _wait_for_job(client, body["job_id"])
    assert job["status"] == "succeeded"
    return body


@pytest.mark.anyio
async def test_over_limit_pdf_marks_document_failed(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_PAGES", "1")
    reset_settings_cache()

    pdf_path = tmp_path / "two-pages.pdf"
    _create_pdf(pdf_path, ["first page", "second page"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client)
        with pdf_path.open("rb") as handle:
            upload_response = await client.post(
                f"/api/courses/{course_id}/materials",
                files={"file": ("two-pages.pdf", handle, "application/pdf")},
            )
        assert upload_response.status_code == 201
        upload_body = upload_response.json()
        job = await _wait_for_job(client, upload_body["job_id"])
        assert job["status"] == "failed"
        assert job["error_code"] == "DOCUMENT_TOO_MANY_PAGES"

        detail = await client.get(f"/api/materials/{upload_body['document_id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "failed"
        assert body["error_code"] == "DOCUMENT_TOO_MANY_PAGES"


@pytest.mark.anyio
async def test_unexpected_quiz_generation_error_marks_quiz_failed(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage5")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(
        pdf_path,
        [
            "Slow start increases the congestion window after timeout.",
            "Congestion avoidance grows the window linearly.",
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Quiz Failure")
        await _upload_pdf_material(client, course_id, pdf_path)
        build_response = await client.post(
            f"/api/courses/{course_id}/knowledge/build", json={}
        )
        assert build_response.status_code == 202
        build_job = await _wait_for_job(client, build_response.json()["job_id"])
        assert build_job["status"] == "succeeded"

        class ExplodingAdapter:
            def ensure_available(self) -> None:
                return None

            def generate_structured_output(self, **kwargs):
                raise RuntimeError("adapter exploded")

        monkeypatch.setattr(
            "app.services.quiz_service.get_llm_adapter",
            lambda: ExplodingAdapter(),
        )

        generate_response = await client.post(
            f"/api/courses/{course_id}/quiz/generate",
            json={
                "question_count": 1,
                "question_types": ["single_choice"],
                "difficulty": "low",
            },
        )
        assert generate_response.status_code == 202
        generate_body = generate_response.json()
        job = await _wait_for_job(client, generate_body["job_id"])
        assert job["status"] == "failed"

        quiz_response = await client.get(f"/api/quizzes/{generate_body['quiz_id']}")
        assert quiz_response.status_code == 200
        assert quiz_response.json()["status"] == "failed"


def test_job_claim_is_unique_under_two_sessions(
    migrated_database_url: str,
) -> None:
    repository = JobRepository()
    with session_scope() as session:
        job = repository.create_job(
            session,
            job_type="quiz.generate",
            payload_json={},
            max_attempts=1,
        )
        session.commit()
        job_id = job.id

    with session_scope() as first_session:
        first = repository.claim_next_available_job(first_session)
    with session_scope() as second_session:
        second = repository.claim_next_available_job(second_session)

    assert first is not None
    assert first.id == job_id
    assert first.attempts == 1
    assert second is None


def test_rubric_total_is_normalized_to_criteria_sum() -> None:
    rubric = QuestionRubric(
        max_points=20,
        criteria=[
            QuestionRubricCriterion(
                criterion_id="c1",
                description="Content",
                max_points=4,
            ),
            QuestionRubricCriterion(
                criterion_id="c2",
                description="Reasoning",
                max_points=2,
            ),
        ],
    )
    normalized = normalize_rubric(rubric)
    assert normalized.max_points == pytest.approx(6)
    assert normalized is not rubric

    with pytest.raises(ValidationError):
        QuestionRubric(
            max_points=0,
            criteria=[QuestionRubricCriterion(
                criterion_id="c1",
                description="Content",
                max_points=1,
            )],
        )


def test_grading_candidate_requires_at_least_one_criterion_score() -> None:
    with pytest.raises(ValidationError):
        ShortAnswerGradingCandidate.model_validate(
            {
                "score": 1,
                "feedback": "ok",
                "rationale": "ok",
            }
        )


@pytest.mark.anyio
async def test_validation_errors_mask_secret_like_input(
    migrated_database_url: str,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/settings",
            json={"apiKey": "sk-test-123"},
        )

    assert response.status_code == 422
    assert "sk-test-123" not in response.text
    assert "apiKey" in response.text
    assert "***" in response.text


def test_delete_course_removes_files_after_commit() -> None:
    class FakeSession:
        committed = False

        def commit(self) -> None:
            self.committed = True

    class FakeRepository:
        def get_course(self, session, course_id):
            return SimpleNamespace(
                documents=[
                    SimpleNamespace(storage_key="documents/a.pdf"),
                    SimpleNamespace(storage_key="documents/a.pdf"),
                    SimpleNamespace(storage_key="documents/b.pdf"),
                ]
            )

        def delete_course(self, session, course) -> None:
            assert session.committed is False

    class FakeStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete(self, storage_key: str) -> None:
            assert session.committed is True
            self.deleted.append(storage_key)

    session = FakeSession()
    storage = FakeStorage()
    service = CourseService(repository=FakeRepository(), storage=storage)
    service.delete_course(session, "course-1")

    assert session.committed is True
    assert storage.deleted == ["documents/a.pdf", "documents/b.pdf"]


@pytest.mark.anyio
async def test_database_busy_error_keeps_error_envelope() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/health",
            "headers": [],
            "state": {"request_id": "req-test"},
        }
    )
    error = OperationalError("SELECT 1", {}, Exception("database is locked"))

    response = await database_busy_handler(request, error)
    body = json.loads(response.body)

    assert response.status_code == 503
    assert body["error"]["code"] == "DATABASE_BUSY"
    assert body["error"]["details"] == {"retryable": True}

