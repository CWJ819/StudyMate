from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models.job import Job
from app.db.models.llm_call import LLMCall
from app.db.session import session_scope
from app.main import app


@pytest.mark.anyio
async def test_job_llm_calls_summary(migrated_database_url: str) -> None:
    job_id = str(uuid4())
    with session_scope() as session:
        session.add(
            Job(
                id=job_id,
                type="knowledge_framework.build",
                status="succeeded",
                payload_json={},
                max_attempts=1,
                run_after=datetime.now(UTC),
            )
        )
        session.flush()
        for purpose, status in (
            ("outline", "succeeded"),
            ("section_extract", "succeeded"),
            ("section_extract", "failed"),
            ("section_extract", "skipped_deadline"),
        ):
            session.add(
                LLMCall(
                    job_id=job_id,
                    purpose=purpose,
                    prompt_version="test",
                    model_name="mock",
                    status=status,
                )
            )
        session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/api/jobs/{job_id}/llm-calls")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "job_id": job_id,
        "total": 4,
        "succeeded": 2,
        "failed": 1,
        "skipped_deadline": 1,
        "by_purpose": [
            {"purpose": "outline", "count": 1},
            {"purpose": "section_extract", "count": 3},
        ],
    }


@pytest.mark.anyio
async def test_job_llm_calls_unknown_job_returns_404(migrated_database_url: str) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/api/jobs/{uuid4()}/llm-calls")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
