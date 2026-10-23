from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_at: datetime | None
    error_code: str | None
    error_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # v5 构建流水线的阶段进度；旧任务/其他任务类型为 None
    phase: str | None = None
    completed_units: int | None = None
    total_units: int | None = None
    message: str | None = None


class LLMCallPurposeCount(BaseModel):
    purpose: str
    count: int


class LLMCallSummaryResponse(BaseModel):
    job_id: str
    total: int
    succeeded: int
    failed: int
    skipped_deadline: int
    by_purpose: list[LLMCallPurposeCount]


class LLMCallPurposeCount(BaseModel):
    purpose: str
    count: int


class LLMCallSummaryResponse(BaseModel):
    job_id: str
    total: int
    succeeded: int
    failed: int
    skipped_deadline: int
    by_purpose: list[LLMCallPurposeCount]
