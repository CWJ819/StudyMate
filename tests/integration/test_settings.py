import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.main import app


@pytest.mark.anyio
async def test_settings_can_be_updated_without_exposing_api_key(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    reset_settings_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        update_response = await client.put(
            "/api/settings",
            json={
                "llm_model": "gpt-test",
                "llm_timeout_seconds": 30,
                "job_max_attempts": 5,
            },
        )
        assert update_response.status_code == 200
        body = update_response.json()
        assert body["llm_model"] == "gpt-test"
        assert body["llm_timeout_seconds"] == 30
        assert body["job_max_attempts"] == 5
        assert body["llm_auth_configured"] is False
        assert "llm_api_key" not in body
    reset_settings_cache()


@pytest.mark.anyio
async def test_settings_reject_api_key_updates(migrated_database_url: str) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/settings",
            json={"llm_api_key": "secret"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "LLM_API_KEY_ENV_ONLY"
