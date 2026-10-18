from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class CourseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    active_framework_version_id: str | None
    created_at: datetime
    updated_at: datetime

