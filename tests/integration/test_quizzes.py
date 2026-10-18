import asyncio
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.config import reset_settings_cache
from app.db.models.quiz import Attempt, Question, Quiz, QuizSubmission
from app.db.session import session_scope
from app.main import app


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


async def _create_course(client: AsyncClient, name: str = "Biology") -> str:
    response = await client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_pdf_material(client: AsyncClient, course_id: str, path: Path) -> str:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": (path.name, handle, "application/pdf")},
        )
    assert response.status_code == 201
    body = response.json()
    job = await _wait_for_job(client, body["job_id"])
    assert job["status"] == "succeeded"
    return body["document_id"]


async def _build_knowledge(client: AsyncClient, course_id: str) -> None:
    response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
    assert response.status_code == 202
    job = await _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"


async def _generate_quiz(
    client: AsyncClient,
    course_id: str,
    *,
    question_count: int,
    question_types: list[str],
) -> dict:
    response = await client.post(
        f"/api/courses/{course_id}/quiz/generate",
        json={
            "question_count": question_count,
            "question_types": question_types,
            "difficulty": "low",
        },
    )
    assert response.status_code == 202
    body = response.json()
    job = await _wait_for_job(client, body["job_id"])
    assert job["status"] == "succeeded"
    return body


def _short_answer_text(question: dict) -> str:
    stem = question["stem"]
    prefix = "Summarize "
    suffix = " in one or two sentences"
    start = stem.index(prefix) + len(prefix)
    end = stem.index(suffix)
    title = stem[start:end]
    return f"{title} is supported by the course material."


@pytest.mark.anyio
async def test_quiz_generation_hides_answers_and_submission_is_idempotent(
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
            "Photosynthesis converts light energy into chemical energy.",
            "Cellular respiration releases stored energy from nutrients.",
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Biology Review")
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)

        generated = await _generate_quiz(
            client,
            course_id,
            question_count=3,
            question_types=["single_choice", "multiple_choice", "short_answer"],
        )
        quiz_response = await client.get(f"/api/quizzes/{generated['quiz_id']}")
        assert quiz_response.status_code == 200
        quiz = quiz_response.json()
        assert quiz["status"] == "open"
        assert len(quiz["questions"]) == 3
        for question in quiz["questions"]:
            assert "answer_key_option_ids" not in question
            assert "reference_answer" not in question
            assert "rubric" not in question
            assert "explanation" not in question
            assert "source_metadata" not in question

        answers = []
        for question in quiz["questions"]:
            if question["question_type"] == "single_choice":
                answers.append(
                    {"question_id": question["question_id"], "selected_option_ids": ["A"]}
                )
            elif question["question_type"] == "multiple_choice":
                answers.append(
                    {"question_id": question["question_id"], "selected_option_ids": ["B", "A"]}
                )
            else:
                answers.append(
                    {"question_id": question["question_id"], "text": _short_answer_text(question)}
                )

        submit_payload = {"idempotency_key": "quiz-submit-1", "answers": answers}
        submit_response = await client.post(
            f"/api/quizzes/{generated['quiz_id']}/submit",
            json=submit_payload,
        )
        assert submit_response.status_code == 200
        submitted = submit_response.json()
        assert submitted["status"] == "submitted"
        assert submitted["total_score"] == submitted["max_score"] == 4.0

        repeated_response = await client.post(
            f"/api/quizzes/{generated['quiz_id']}/submit",
            json=submit_payload,
        )
        assert repeated_response.status_code == 200
        assert repeated_response.json() == submitted

        conflict_response = await client.post(
            f"/api/quizzes/{generated['quiz_id']}/submit",
            json={"idempotency_key": "quiz-submit-1", "answers": answers[:-1]},
        )
        assert conflict_response.status_code == 409
        assert conflict_response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

        repeated_results = await asyncio.gather(
            client.post(f"/api/quizzes/{generated['quiz_id']}/submit", json=submit_payload),
            client.post(f"/api/quizzes/{generated['quiz_id']}/submit", json=submit_payload),
        )
        assert [response.status_code for response in repeated_results] == [200, 200]
        assert repeated_results[0].json() == submitted
        assert repeated_results[1].json() == submitted

        with session_scope() as session:
            submission_count = session.scalar(
                select(func.count(QuizSubmission.id)).where(
                    QuizSubmission.quiz_id == generated["quiz_id"]
                )
            )
            attempt_count = session.scalar(
                select(func.count(Attempt.id)).where(Attempt.quiz_id == generated["quiz_id"])
            )
        assert submission_count == 1
        assert attempt_count == len(answers)

    reset_settings_cache()


@pytest.mark.anyio
async def test_quiz_generation_deduplicates_against_historical_questions(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage5")
    reset_settings_cache()

    pdf_path = tmp_path / "history.pdf"
    _create_pdf(pdf_path, ["Newton's laws describe motion and force."])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Mechanics")
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)

        first_quiz = await _generate_quiz(
            client,
            course_id,
            question_count=2,
            question_types=["single_choice", "multiple_choice"],
        )
        second_quiz = await _generate_quiz(
            client,
            course_id,
            question_count=2,
            question_types=["single_choice", "multiple_choice"],
        )

        first_questions = (
            await client.get(f"/api/quizzes/{first_quiz['quiz_id']}")
        ).json()["questions"]
        second_questions = (
            await client.get(f"/api/quizzes/{second_quiz['quiz_id']}")
        ).json()["questions"]

        first_stems = {question["stem"] for question in first_questions}
        second_stems = {question["stem"] for question in second_questions}
        assert first_stems.isdisjoint(second_stems)

    reset_settings_cache()


@pytest.mark.anyio
async def test_quiz_generation_fails_for_invalid_structured_output(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage5")
    reset_settings_cache()

    pdf_path = tmp_path / "fallback.pdf"
    _create_pdf(pdf_path, ["Cache locality improves memory hierarchy performance."])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Computer Systems")
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)

        class InvalidQuizAdapter:
            def ensure_available(self) -> None:
                return None

            def generate_structured_output(self, **kwargs):
                if kwargs["prompt_version"] == "quiz-generation-v3":
                    raise AppError(
                        code="LLM_OUTPUT_INVALID",
                        message="LLM returned invalid structured output.",
                        status_code=502,
                    )
                raise AssertionError("Unexpected adapter call")

        monkeypatch.setattr(
            "app.services.quiz_service.get_llm_adapter",
            lambda: InvalidQuizAdapter(),
        )

        response = await client.post(
            f"/api/courses/{course_id}/quiz/generate",
            json={
                "question_count": 2,
                "question_types": ["single_choice", "multiple_choice"],
                "difficulty": "low",
            },
        )
        assert response.status_code == 202
        job = await _wait_for_job(client, response.json()["job_id"])
        assert job["status"] == "failed"
        assert job["error_code"] == "LLM_OUTPUT_INVALID"

    reset_settings_cache()


@pytest.mark.anyio
async def test_quiz_uses_snapshot_after_question_record_changes(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage5")
    reset_settings_cache()

    pdf_path = tmp_path / "snapshot.pdf"
    _create_pdf(pdf_path, ["Chemical bonds hold atoms together."])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Chemistry")
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)

        generated = await _generate_quiz(
            client,
            course_id,
            question_count=1,
            question_types=["single_choice"],
        )
        initial_quiz = (await client.get(f"/api/quizzes/{generated['quiz_id']}")).json()
        initial_stem = initial_quiz["questions"][0]["stem"]

        with session_scope() as session:
            quiz = session.get(Quiz, generated["quiz_id"])
            assert quiz is not None
            question_id = quiz.quiz_questions[0].question_id
            question = session.get(Question, question_id)
            assert question is not None
            question.stem = "This stem was edited after the quiz was created."
            session.commit()

        snapshot_quiz = (await client.get(f"/api/quizzes/{generated['quiz_id']}")).json()
        assert snapshot_quiz["questions"][0]["stem"] == initial_stem

    reset_settings_cache()
