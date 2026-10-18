from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class StudyPlanGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam_date: date
    daily_minutes: int = Field(ge=15, le=720)
    target_score: int = Field(ge=0, le=100)
    knowledge_node_ids: list[str] = Field(default_factory=list, max_length=100)


class StudyTaskTargetResponse(BaseModel):
    knowledge_node_id: str
    title: str | None = None
    target_role: str


class StudyTaskResponse(BaseModel):
    id: str
    title: str
    task_type: str
    scheduled_date: date
    estimated_minutes: int
    priority: int
    status: str
    targets: list[StudyTaskTargetResponse]


class StudyPlanSummaryResponse(BaseModel):
    id: str
    course_id: str
    version_number: int
    exam_date: date
    daily_minutes: int
    target_score: int
    status: str
    task_count: int
    created_at: datetime


class StudyPlanDetailResponse(BaseModel):
    id: str
    course_id: str
    version_number: int
    exam_date: date
    daily_minutes: int
    target_score: int
    status: str
    constraints: dict
    created_at: datetime
    tasks: list[StudyTaskResponse]


class StudyTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=50)
