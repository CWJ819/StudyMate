from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(default="sqlite:///./data/studymate.db", alias="DATABASE_URL")
    storage_root: Path = Field(default=Path("./data/uploads"), alias="STORAGE_ROOT")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    max_document_pages: int = Field(default=500, alias="MAX_DOCUMENT_PAGES")
    job_max_attempts: int = Field(default=3, alias="JOB_MAX_ATTEMPTS")
    job_poll_interval_seconds: int = Field(default=1, alias="JOB_POLL_INTERVAL_SECONDS")
    job_lock_timeout_seconds: int = Field(default=300, alias="JOB_LOCK_TIMEOUT_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
