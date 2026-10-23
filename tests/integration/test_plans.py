import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.main import app
from app.services.plan_service import PlanService

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


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


async def _create_course(client: AsyncClient, name: str = "Planning") -> str:
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


@pytest.mark.anyio
async def test_study_plan_generation_versions_time_limit_and_task_status(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "mock://local")
    monkeypatch.setenv("LLM_MODEL", "mock-stage7")
    reset_settings_cache()

    pdf_path = tmp_path / "lesson.pdf"
    _create_pdf(pdf_path, ["Integration by parts transforms products of functions."])
    exam_date = datetime.now(LOCAL_TZ).date() + timedelta(days=7)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_id = await _create_course(client, name="Calculus Plan")
        await _upload_pdf_material(client, course_id, pdf_path)
        await _build_knowledge(client, course_id)

        first_response = await client.post(
            f"/api/courses/{course_id}/plan",
            json={
                "exam_date": exam_date.isoformat(),
                "daily_minutes": 30,
                "target_score": 85,
            },
        )
        assert first_response.status_code == 201
        first_plan = first_response.json()
        assert first_plan["version_number"] == 1
        assert first_plan["status"] == "active"
        assert len(first_plan["tasks"]) == 1
        assert first_plan["tasks"][0]["task_type"] == "review"
        assert first_plan["tasks"][0]["estimated_minutes"] >= 8

        daily_totals = defaultdict(int)
        for task in first_plan["tasks"]:
            daily_totals[task["scheduled_date"]] += task["estimated_minutes"]
        assert all(total <= first_plan["daily_minutes"] for total in daily_totals.values())

        task_id = first_plan["tasks"][0]["id"]
        update_response = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "in_progress"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["status"] == "in_progress"

        complete_response = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "completed"},
        )
        assert complete_response.status_code == 200
        assert complete_response.json()["status"] == "completed"

        invalid_transition_response = await client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "pending"},
        )
        assert invalid_transition_response.status_code == 409
        assert invalid_transition_response.json()["error"]["code"] == "INVALID_TASK_STATUS_TRANSITION"

        second_response = await client.post(
            f"/api/courses/{course_id}/plan",
            json={
                "exam_date": exam_date.isoformat(),
                "daily_minutes": 30,
                "target_score": 90,
            },
        )
        assert second_response.status_code == 201
        second_plan = second_response.json()
        assert second_plan["version_number"] == 2
        assert second_plan["id"] != first_plan["id"]

        list_response = await client.get(f"/api/courses/{course_id}/plans")
        assert list_response.status_code == 200
        plans = list_response.json()
        assert [plan["version_number"] for plan in plans] == [2, 1]
        assert [plan["status"] for plan in plans] == ["active", "inactive"]

        first_detail_response = await client.get(f"/api/plans/{first_plan['id']}")
        assert first_detail_response.status_code == 200
        assert first_detail_response.json()["tasks"][0]["status"] == "completed"

        original_build = PlanService._build_task_specs

        def oversized_specs(self, nodes):  # type: ignore[no-untyped-def]
            return [
                {
                    "title": "Oversized review",
                    "task_type": "review",
                    "estimated_minutes": 16,
                    "priority": 1,
                    "knowledge_node_id": nodes[0].knowledge_node_id,
                    "target_role": "primary",
                }
            ]

        monkeypatch.setattr(PlanService, "_build_task_specs", oversized_specs)
        capacity_response = await client.post(
            f"/api/courses/{course_id}/plan",
            json={
                "exam_date": datetime.now(LOCAL_TZ).date().isoformat(),
                "daily_minutes": 15,
                "target_score": 90,
            },
        )
        assert capacity_response.status_code == 409
        assert capacity_response.json()["error"]["code"] == "PLAN_CAPACITY_EXCEEDED"
        monkeypatch.setattr(PlanService, "_build_task_specs", original_build)

    reset_settings_cache()
