import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
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
async def test_upload_to_plan_end_to_end_flow(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage8")
    reset_settings_cache()

    pdf_path = tmp_path / "stage8.pdf"
    _create_pdf(
        pdf_path,
        [
            "Quadratic equations can be solved by factoring or completing the square.",
            "The discriminant determines the number of real roots.",
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_response = await client.post("/api/courses", json={"name": "Stage 8 Math"})
        assert course_response.status_code == 201
        course_id = course_response.json()["id"]

        with pdf_path.open("rb") as handle:
            upload_response = await client.post(
                f"/api/courses/{course_id}/materials",
                files={"file": (pdf_path.name, handle, "application/pdf")},
            )
        assert upload_response.status_code == 201
        material_job = await _wait_for_job(client, upload_response.json()["job_id"])
        assert material_job["status"] == "succeeded"

        material_response = await client.get(f"/api/materials/{upload_response.json()['document_id']}")
        assert material_response.status_code == 200
        material = material_response.json()
        assert material["status"] == "completed"
        assert [page["page_number"] for page in material["pages"]] == [1, 2]

        knowledge_response = await client.post(f"/api/courses/{course_id}/knowledge/build", json={})
        assert knowledge_response.status_code == 202
        knowledge_job = await _wait_for_job(client, knowledge_response.json()["job_id"])
        assert knowledge_job["status"] == "succeeded"

        framework_response = await client.get(f"/api/courses/{course_id}/knowledge")
        assert framework_response.status_code == 200
        framework = framework_response.json()
        assert framework["status"] == "active"
        assert framework["nodes"]

        quiz_id = await _generate_quiz(client, course_id)
        quiz_response = await client.get(f"/api/quizzes/{quiz_id}")
        assert quiz_response.status_code == 200
        quiz = quiz_response.json()
        assert quiz["status"] == "open"
        assert len(quiz["questions"]) == 2

        answers = []
        for question in quiz["questions"]:
            if question["question_type"] == "single_choice":
                answers.append({"question_id": question["question_id"], "selected_option_ids": ["A"]})
            else:
                answers.append(
                    {"question_id": question["question_id"], "selected_option_ids": ["A", "B"]}
                )

        submit_response = await client.post(
            f"/api/quizzes/{quiz_id}/submit",
            json={"idempotency_key": "stage8-e2e-submit", "answers": answers},
        )
        assert submit_response.status_code == 200
        submitted = submit_response.json()
        assert submitted["status"] == "submitted"
        assert submitted["total_score"] == submitted["max_score"]

        mastery_response = await client.get(f"/api/courses/{course_id}/mastery")
        assert mastery_response.status_code == 200
        mastery = mastery_response.json()
        assert mastery
        assert mastery[0]["evidence_count"] >= 1

        targets_response = await client.post(
            f"/api/courses/{course_id}/review-targets",
            json={"limit": 3, "exploration_ratio": 0.3},
        )
        assert targets_response.status_code == 200
        assert targets_response.json()["targets"]

        plan_response = await client.post(
            f"/api/courses/{course_id}/plan",
            json={
                "exam_date": (datetime.now(UTC).date() + timedelta(days=7)).isoformat(),
                "daily_minutes": 30,
                "target_score": 90,
            },
        )
        assert plan_response.status_code == 201
        plan = plan_response.json()
        assert plan["status"] == "active"
        assert plan["tasks"]
        daily_totals: dict[str, int] = {}
        for task in plan["tasks"]:
            daily_totals[task["scheduled_date"]] = (
                daily_totals.get(task["scheduled_date"], 0) + task["estimated_minutes"]
            )
            assert task["targets"]
        assert all(total <= plan["daily_minutes"] for total in daily_totals.values())

    reset_settings_cache()
