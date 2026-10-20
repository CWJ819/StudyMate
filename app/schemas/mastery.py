from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MasteryStateResponse(BaseModel):
    knowledge_node_id: str
    node_version_id: str | None = None
    parent_id: str | None = None
    section_path: list[str] = Field(default_factory=list)
    title: str | None
    alpha: float
    beta: float
    mastery_estimate: float
    evidence_count: int
    updated_at: datetime


class KnowledgeGapResponse(BaseModel):
    gap_id: str
    knowledge_node_id: str
    node_version_id: str
    title: str
    section_path: list[str] = Field(default_factory=list)
    gap_type: str
    status: str
    confidence: float
    evidence_count: int
    evidence_summary: dict
    updated_at: datetime


class ReviewTargetsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=50)
    exploration_ratio: float = Field(default=0.3, ge=0, le=1)


class ReviewTargetResponse(BaseModel):
    knowledge_node_id: str
    node_version_id: str
    title: str
    section_path: list[str] = Field(default_factory=list)
    priority: float
    mastery_estimate: float | None
    evidence_count: int
    reason: str


class ReviewTargetsResponse(BaseModel):
    strategy_log_id: str
    strategy_version: str
    targets: list[ReviewTargetResponse]


class ChapterMasterySummaryResponse(BaseModel):
    node_version_id: str
    title: str
    level: int
    section_path: list[str] = Field(default_factory=list)
    total_leaves: int
    tested_leaves: int
    untested_leaves: int
    coverage: float
    average_mastery: float | None
    low_mastery_leaves: int
    weak_density: float
    priority: float


class MasteryOverviewResponse(BaseModel):
    chapters: list[ChapterMasterySummaryResponse]
