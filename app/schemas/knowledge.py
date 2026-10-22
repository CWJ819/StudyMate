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


class KnowledgeGraphNodeResponse(BaseModel):
    knowledge_node_id: str
    title: str
    # 从顶层章到叶子的容器标题路径（不含课程根节点）
    section_path: list[str]
    is_leaf: bool


class KnowledgeGraphEdgeResponse(BaseModel):
    # source/target 都是 knowledge_node_id，供关系图视图直接连边
    source: str
    target: str
    relation_type: str
    confidence: float
    evidence: str | None


class KnowledgeGraphResponse(BaseModel):
    framework_version_id: str
    nodes: list[KnowledgeGraphNodeResponse]
    edges: list[KnowledgeGraphEdgeResponse]


class KnowledgeScoreReasonResponse(BaseModel):
    """一个评分分量的解释：原值、归一化值、加权贡献。"""

    component: str
    value: int | float
    normalized: float
    contribution: float


class KnowledgeScoredTreeNodeResponse(KnowledgeTreeNodeResponse):
    """与 GET /knowledge 的树节点同形，另加读取时计算的分数。

    importance / difficulty 是工程估计值，不是对课程内容的精确测量。
    容器取后代最大值（语义：“本章最重要 0.82”）；components 只给叶子
    （四分量原值），容器为 null。
    """

    importance: float
    difficulty: float
    components: dict[str, int | float] | None = None
    children: list["KnowledgeScoredTreeNodeResponse"] = Field(default_factory=list)


class KnowledgeScoredTreeResponse(BaseModel):
    framework_version_id: str
    version_number: int
    scoring_version: str
    tree: list[KnowledgeScoredTreeNodeResponse]


class KnowledgeHighlightItemResponse(BaseModel):
    knowledge_node_id: str
    title: str
    section_path: list[str]
    importance: float
    difficulty: float
    # 掌握度同样只是估计值；None 表示该叶还没有作答证据（untested=True）。
    mastery_estimate: float | None
    evidence_count: int
    untested: bool
    reasons: list[KnowledgeScoreReasonResponse]


class KnowledgeScoringWeightsResponse(BaseModel):
    importance: dict[str, float]
    difficulty: dict[str, float]


class KnowledgeScoringBasisResponse(BaseModel):
    scoring_version: str
    weights: KnowledgeScoringWeightsResponse


class KnowledgeHighlightsResponse(BaseModel):
    items: list[KnowledgeHighlightItemResponse]
    basis: KnowledgeScoringBasisResponse
