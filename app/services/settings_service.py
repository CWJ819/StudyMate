from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.repositories.settings_repository import SettingsRepository
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest

OVERRIDABLE_SETTINGS = {
    "llm_base_url",
    "llm_model",
    "llm_timeout_seconds",
    "llm_max_retries",
    "max_upload_bytes",
    "max_document_pages",
    "job_max_attempts",
}


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
            llm_auth_configured=bool(settings.llm_api_key),
        )

    def update_settings(
        self, session: Session, payload: SettingsUpdateRequest
    ) -> SettingsResponse:
        if payload.llm_api_key is not None:
            raise AppError(
                code="LLM_API_KEY_ENV_ONLY",
                message="LLM API keys are managed through local environment variables only.",
                status_code=400,
            )

        update_values = payload.model_dump(
            exclude_none=True,
            exclude={"llm_api_key"},
        )
        if update_values:
            self.repository.upsert_many(session, update_values)
            session.commit()

        return self.read_settings(session)

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
