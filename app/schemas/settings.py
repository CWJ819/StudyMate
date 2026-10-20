from typing import Literal

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
    # 只报告来源，绝不返回密钥本身；local = 设置页保存在本机，environment = 环境变量
    llm_api_key_source: Literal["local", "environment"] | None = None


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    llm_max_retries: int | None = Field(default=None, ge=0, le=10)
    max_upload_bytes: int | None = Field(default=None, ge=1)
    max_document_pages: int | None = Field(default=None, ge=1)
    job_max_attempts: int | None = Field(default=None, ge=1, le=20)
    # 本地单机产品允许页面写入；空字符串表示清除本机保存的 Key。
    # 不设长度/格式 Field 约束，避免校验失败时 422 把密钥原文回显出来。
    llm_api_key: str | None = None
