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
