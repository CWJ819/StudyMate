import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.main import app


@pytest.mark.anyio
async def test_upload_rejects_path_traversal_filename(
    migrated_database_url: str,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        course_response = await client.post("/api/courses", json={"name": "Security"})
        assert course_response.status_code == 201
        course_id = course_response.json()["id"]

        response = await client.post(
            f"/api/courses/{course_id}/materials",
            files={"file": ("../evil.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILENAME"


@pytest.mark.anyio
async def test_error_and_settings_responses_do_not_leak_llm_api_key(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "stage8-super-secret-key"
    monkeypatch.setenv("LLM_API_KEY", secret)
    reset_settings_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        settings_response = await client.get("/api/settings")
        error_response = await client.post(
            "/api/courses/missing-course/materials",
            files={"file": ("../secret.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

    assert settings_response.status_code == 200
    assert settings_response.json()["llm_auth_configured"] is True
    assert settings_response.json()["llm_api_key_source"] == "environment"
    assert secret not in settings_response.text
    # 只允许出现来源字段名，不能出现密钥字段
    assert '"llm_api_key":' not in settings_response.text
    assert error_response.status_code == 404
    assert secret not in error_response.text

    reset_settings_cache()
