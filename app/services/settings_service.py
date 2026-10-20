import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import session_scope
from app.repositories.settings_repository import SettingsRepository
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest
from app.services.local_secrets import read_local_api_key, write_local_api_key

logger = logging.getLogger(__name__)

OVERRIDABLE_SETTINGS = {
    "llm_base_url",
    "llm_model",
    "llm_timeout_seconds",
    "llm_max_retries",
    "max_upload_bytes",
    "max_document_pages",
    "job_max_attempts",
}

# 页面可改且必须对后续 LLM 调用立即生效的普通键。API Key 不在这个表里：
# 它单独保存在数据库同目录的 local_secrets.json（见 app/services/local_secrets.py）。
LLM_RUNTIME_KEYS = {
    "llm_base_url",
    "llm_model",
    "llm_timeout_seconds",
    "llm_max_retries",
}


def read_llm_runtime_overrides() -> dict[str, Any]:
    """读取 PUT /api/settings 写入数据库的 LLM 运行时覆盖（env 之上的优先层）。"""
    with session_scope() as session:
        raw = SettingsRepository().get_many(session, LLM_RUNTIME_KEYS)

    overrides: dict[str, Any] = {}
    for key in ("llm_base_url", "llm_model"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            overrides[key] = value
    for key in ("llm_timeout_seconds", "llm_max_retries"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            overrides[key] = int(value)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid settings override %s=%r", key, value)
    return overrides


@dataclass(frozen=True)
class EffectiveSettings:
    llm_base_url: str | None
    llm_model: str | None
    llm_timeout_seconds: int
    llm_max_retries: int
    max_upload_bytes: int
    max_document_pages: int
    job_max_attempts: int


class SettingsService:
    def __init__(self, repository: SettingsRepository | None = None) -> None:
        self.repository = repository or SettingsRepository()

    def read_settings(self, session: Session) -> SettingsResponse:
        settings = get_settings()
        effective = self._effective_settings(session, settings)
        local_api_key = read_local_api_key()
        return SettingsResponse(
            app_env=settings.app_env,
            database_url=settings.database_url,
            storage_root=str(settings.storage_root),
            llm_base_url=effective.llm_base_url,
            llm_model=effective.llm_model,
            llm_timeout_seconds=effective.llm_timeout_seconds,
            llm_max_retries=effective.llm_max_retries,
            max_upload_bytes=effective.max_upload_bytes,
            max_document_pages=effective.max_document_pages,
            job_max_attempts=effective.job_max_attempts,
            llm_auth_configured=bool(local_api_key or settings.llm_api_key),
            llm_api_key_source=(
                "local" if local_api_key else ("environment" if settings.llm_api_key else None)
            ),
        )

    def update_settings(
        self, session: Session, payload: SettingsUpdateRequest
    ) -> SettingsResponse:
        if payload.llm_api_key is not None:
            self._save_local_api_key(payload.llm_api_key)

        update_values = payload.model_dump(
            exclude_none=True,
            exclude={"llm_api_key"},
        )
        if update_values:
            self.repository.upsert_many(session, update_values)
            session.commit()

        return self.read_settings(session)

    def _save_local_api_key(self, raw_api_key: str) -> None:
        api_key = raw_api_key.strip()
        # 密钥会放进 HTTP Authorization 头：拒绝换行，避免头注入。
        if any(character in api_key for character in ("\r", "\n")):
            raise AppError(
                code="INVALID_LLM_API_KEY",
                message="LLM API key must not contain line breaks.",
                status_code=400,
            )
        if len(api_key) > 4096:
            raise AppError(
                code="INVALID_LLM_API_KEY",
                message="LLM API key is too long.",
                status_code=400,
            )
        try:
            write_local_api_key(api_key)
        except OSError as exc:
            raise AppError(
                code="LOCAL_SECRETS_WRITE_FAILED",
                message="Failed to save the LLM API key to the local secrets file.",
                status_code=500,
            ) from exc

    def _effective_settings(
        self, session: Session, settings: Settings
    ) -> EffectiveSettings:
        overrides = self.repository.get_many(session, OVERRIDABLE_SETTINGS)
        return EffectiveSettings(
            llm_base_url=overrides.get("llm_base_url", settings.llm_base_url),
            llm_model=overrides.get("llm_model", settings.llm_model),
            llm_timeout_seconds=int(
                overrides.get("llm_timeout_seconds", settings.llm_timeout_seconds)
            ),
            llm_max_retries=int(
                overrides.get("llm_max_retries", settings.llm_max_retries)
            ),
            max_upload_bytes=int(
                overrides.get("max_upload_bytes", settings.max_upload_bytes)
            ),
            max_document_pages=int(
                overrides.get("max_document_pages", settings.max_document_pages)
            ),
            job_max_attempts=int(
                overrides.get("job_max_attempts", settings.job_max_attempts)
            ),
        )
