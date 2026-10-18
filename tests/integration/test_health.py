from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.db.session import reset_session_state
from app.main import app


@pytest.mark.anyio
async def test_health_check_reports_application_and_database_ok(
    migrated_database_url: str,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "application": "ok",
            "database": "ok",
            "environment": "development",
        }
        assert response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_settings_route_masks_llm_api_key_value(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    reset_settings_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/settings")

        assert response.status_code == 200
        body = response.json()
        assert "llm_api_key" not in body
        assert body["llm_auth_configured"] is False
    reset_settings_cache()


@pytest.mark.anyio
async def test_health_check_reports_outdated_database_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "outdated.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "uploads"))
    reset_settings_cache()
    reset_session_state()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20261017_0007")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DATABASE_SCHEMA_OUTDATED"
    assert body["error"]["details"]["current_revision"] == "20261017_0007"
    assert "20261018_0009" in body["error"]["details"]["head_revisions"]

    reset_session_state()
    reset_settings_cache()
