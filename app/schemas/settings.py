from pydantic import BaseModel, ConfigDict, Field


class SettingsResponse(BaseModel):
    app_env: str
    database_url: str
    storage_root: str
    llm_base_url: str | None
    llm_model: str | None
    llm_timeout_seconds: int
    llm_max_retries: int
    max_upload_bytes: int
    max_document_pages: int
    job_max_attempts: int
    llm_auth_configured: bool


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    llm_max_retries: int | None = Field(default=None, ge=0, le=10)
    max_upload_bytes: int | None = Field(default=None, ge=1)
    max_document_pages: int | None = Field(default=None, ge=1)
    job_max_attempts: int | None = Field(default=None, ge=1, le=20)
    llm_api_key: str | None = None
