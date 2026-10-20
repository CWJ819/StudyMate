from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_outline: str | None = None


class KnowledgeBuildResponse(BaseModel):
    job_id: str
    framework_version_id: str
    status: str


class KnowledgeVersionResponse(BaseModel):
    id: str
    version_number: int
    status: str
    created_at: datetime
    activated_at: datetime | None
    input_revision: int


class KnowledgeSourceResponse(BaseModel):
    document_id: str
    filename: str
    page_number: int
    chunk_id: str | None
    evidence_type: str


class KnowledgeRelationResponse(BaseModel):
    target_knowledge_node_id: str
    target_title: str
    relation_type: str
    confidence: float
    evidence: str | None


class KnowledgeTreeNodeResponse(BaseModel):
    knowledge_node_id: str
    node_version_id: str
    section_label: str | None
    title: str
    content: str | None
    level: int
    is_leaf: bool
    sources: list[KnowledgeSourceResponse]
    children: list["KnowledgeTreeNodeResponse"] = Field(default_factory=list)


class KnowledgeFrameworkResponse(BaseModel):
    framework_version_id: str
    version_number: int
    status: str
    activated_at: datetime | None
    tree: list[KnowledgeTreeNodeResponse]
    nodes: list[KnowledgeTreeNodeResponse]


class KnowledgeNodeDetailResponse(BaseModel):
    knowledge_node_id: str
    node_version_id: str
    framework_version_id: str
    section_label: str | None
    title: str
    content: str | None
    level: int
    is_leaf: bool
    sources: list[KnowledgeSourceResponse]
    relations: list[KnowledgeRelationResponse]


class KnowledgeIdentityMatchResponse(BaseModel):
    current_node_id: str
    current_title: str
    previous_node_id: str | None
    previous_title: str | None
    confidence: float
    match_type: str
    safe_to_migrate: bool


class KnowledgeIdentityDiagnosticsResponse(BaseModel):
    current_version_id: str
    previous_version_id: str | None
    matches: list[KnowledgeIdentityMatchResponse]
