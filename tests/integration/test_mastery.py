import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import reset_settings_cache
from app.db.models.knowledge import KnowledgeNode
from app.db.models.mastery import MasteryEvent, ReviewStrategyLog, StudentGapState
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


async def _upload_pdf_material(client: AsyncClient, course_id: str, path: Path) -> None:
    with path.open("rb") as handle:
        response = await client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": (path.name, handle, "application/pdf")},
        )
    assert response.status_code == 201
    job = await _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"


async def _build_knowledge(client: AsyncClient, course_id: str) -> None:
    response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
    assert response.status_code == 202
    job = await _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"


async def _generate_quiz(client: AsyncClient, course_id: str) -> str:
    response = await client.post(
        f"/api/courses/{course_id}/quiz/generate",
        json={
            "question_count": 2,
            "question_types": ["single_choice", "multiple_choice"],
            "difficulty": "low",
        },
    )
    assert response.status_code == 202
    body = response.json()
    job = await _wait_for_job(client, body["job_id"])
    assert job["status"] == "succeeded"
    return body["quiz_id"]


@pytest.mark.anyio
async def test_quiz_submission_updates_mastery_gaps_and_review_targets(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage6")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(pdf_path, ["Diffusion moves particles from high to low concentration."])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Cells")
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)
        quiz_id = await _generate_quiz(client, course_id)

        quiz_response = await client.get(f"/api/quizzes/{quiz_id}")
        assert quiz_response.status_code == 200
        questions = quiz_response.json()["questions"]
        answers = []
        for question in questions:
            if question["question_type"] == "single_choice":
                answers.append(
                    {"question_id": question["question_id"], "selected_option_ids": ["B"]}
                )
            else:
                answers.append(
                    {"question_id": question["question_id"], "selected_option_ids": ["A", "B"]}
                )

        submit_payload = {"idempotency_key": "stage6-submit", "answers": answers}
        submit_response = await client.post(f"/api/quizzes/{quiz_id}/submit", json=submit_payload)
        assert submit_response.status_code == 200
        assert submit_response.json()["total_score"] == 1.0

        repeated_response = await client.post(f"/api/quizzes/{quiz_id}/submit", json=submit_payload)
        assert repeated_response.status_code == 200
        assert repeated_response.json() == submit_response.json()

        mastery_response = await client.get(f"/api/courses/{course_id}/mastery")
        assert mastery_response.status_code == 200
        mastery = mastery_response.json()
        assert len(mastery) == 1
        assert mastery[0]["evidence_count"] == 2
        assert mastery[0]["alpha"] == 3.0
        assert mastery[0]["beta"] == 3.0
        assert mastery[0]["mastery_estimate"] == 0.5

        wrongbook_response = await client.get(f"/api/courses/{course_id}/wrongbook")
        assert wrongbook_response.status_code == 200
        gaps = wrongbook_response.json()
        assert len(gaps) == 1
        assert gaps[0]["gap_type"] == "low_score"
        assert gaps[0]["status"] in {"suspected", "improving"}
        assert gaps[0]["evidence_count"] == 1
        assert gaps[0]["evidence_summary"]["low_score_evidence"] == 1

        targets_response = await client.post(
            f"/api/courses/{course_id}/review-targets",
            json={"limit": 5, "exploration_ratio": 0.3},
        )
        assert targets_response.status_code == 200
        targets = targets_response.json()
        assert targets["strategy_version"] == "weakness-exploration-v1"
        assert targets["targets"]
        assert targets["targets"][0]["knowledge_node_id"] == mastery[0]["knowledge_node_id"]

    with session_scope() as session:
        event_count = session.scalar(select(func.count(MasteryEvent.id)))
        strategy_log_count = session.scalar(select(func.count(ReviewStrategyLog.id)))
    assert event_count == 2
    assert strategy_log_count == 1

    # 孤儿掌握度：节点不在活动框架里（换模型/重建后常见），接口不能返回空标题行
    with session_scope() as session:
        orphan_node = KnowledgeNode(
            id=str(uuid4()), course_id=course_id, stable_key=f"orphan:{uuid4()}"
        )
        session.add(orphan_node)
        session.flush()
        session.add(
            StudentGapState(
                id=str(uuid4()),
                course_id=course_id,
                knowledge_node_id=orphan_node.id,
                alpha=2.0,
                beta=9.0,
                mastery_estimate=0.2,
                evidence_count=3,
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        filtered = await client.get(f"/api/courses/{course_id}/mastery")
        assert filtered.status_code == 200
        assert [row["knowledge_node_id"] for row in filtered.json()] == [
            mastery[0]["knowledge_node_id"]
        ]
        assert all(row["title"] for row in filtered.json())

    with session_scope() as session:
        assert session.scalar(select(func.count(StudentGapState.id))) == 2  # DB 记录保留

    reset_settings_cache()
