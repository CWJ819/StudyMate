import json
import os
import stat
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import reset_settings_cache
from app.llm.openai_compatible import OpenAICompatibleAdapter
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
async def test_settings_store_api_key_locally_without_returning_it(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地单机产品：Key 存本机文件、不进普通设置表、不经响应回传、下一次调用生效。"""
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    reset_settings_cache()

    secret = "sk-local-secret-123456"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put("/api/settings", json={"llm_api_key": secret})
        assert response.status_code == 200
        body = response.json()
        assert body["llm_auth_configured"] is True
        assert body["llm_api_key_source"] == "local"
        assert "llm_api_key" not in body
        assert secret not in response.text

        get_response = await client.get("/api/settings")
        assert get_response.status_code == 200
        assert get_response.json()["llm_auth_configured"] is True
        assert get_response.json()["llm_api_key_source"] == "local"
        assert secret not in get_response.text

    secrets_file = tmp_path / "local_secrets.json"
    assert json.loads(secrets_file.read_text(encoding="utf-8"))["llm_api_key"] == secret
    if os.name != "nt":
        assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600

    adapter = OpenAICompatibleAdapter()
    assert adapter.settings.llm_api_key == secret
    reset_settings_cache()


@pytest.mark.anyio
async def test_local_api_key_overrides_environment_and_can_be_cleared(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "env-secret")
    reset_settings_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        env_settings = (await client.get("/api/settings")).json()
        assert env_settings["llm_auth_configured"] is True
        assert env_settings["llm_api_key_source"] == "environment"

        saved = await client.put("/api/settings", json={"llm_api_key": "local-secret"})
        assert saved.status_code == 200
        assert saved.json()["llm_api_key_source"] == "local"

        cleared = await client.put("/api/settings", json={"llm_api_key": ""})
        assert cleared.status_code == 200
        assert cleared.json()["llm_auth_configured"] is True
        assert cleared.json()["llm_api_key_source"] == "environment"

    assert not (tmp_path / "local_secrets.json").exists()
    reset_settings_cache()


@pytest.mark.anyio
async def test_settings_reject_multiline_api_key_without_echoing_it(
    migrated_database_url: str,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/settings",
            json={"llm_api_key": "sk-bad\nInjected: value"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_LLM_API_KEY"
        assert "sk-bad" not in response.text


@pytest.mark.anyio
async def test_saved_overrides_apply_to_next_llm_adapter(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """设置页保存的 base_url/model 必须被新建的 LLM 适配器采用，否则页面保存是无效的。"""
    monkeypatch.setenv("LLM_BASE_URL", "http://env-default.test")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    reset_settings_cache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/settings",
            json={
                "llm_base_url": "https://api.deepseek.com",
                "llm_model": "deepseek-chat",
                "llm_timeout_seconds": 45,
                "llm_max_retries": 1,
            },
        )
        assert response.status_code == 200

    adapter = OpenAICompatibleAdapter()
    assert adapter.settings.llm_base_url == "https://api.deepseek.com"
    assert adapter.settings.llm_model == "deepseek-chat"
    assert adapter.settings.llm_timeout_seconds == 45
    assert adapter.settings.llm_max_retries == 1
    reset_settings_cache()
