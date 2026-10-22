from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T", bound=BaseModel)


class LLMRunSummary(BaseModel):
    model_name: str
    prompt_version: str
    provider: str
    # 逻辑调用级观测（v5）：整体耗时与实际尝试次数；旧调用方不填则为 NULL。
    latency_ms: int | None = None
    attempts: int | None = None


class LLMStructuredResult(BaseModel, Generic[T]):
    summary: LLMRunSummary
    data: T


class KnowledgeSourceCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_id: str
    page_number: int = Field(ge=1)
    chunk_id: str | None = None
    evidence_type: str = "page_excerpt"


class KnowledgeNodeCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: str
    section_label: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    content: str | None = None
    sources: list[KnowledgeSourceCandidate] = Field(default_factory=list)
    children: list["KnowledgeNodeCandidate"] = Field(default_factory=list)


class KnowledgeRelationCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_ref: str
    target_ref: str
    relation_type: str
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None


class KnowledgeFrameworkCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root_title: str = Field(min_length=1, max_length=255)
    root_description: str | None = None
    nodes: list[KnowledgeNodeCandidate] = Field(default_factory=list)
    relations: list[KnowledgeRelationCandidate] = Field(default_factory=list)


class KnowledgeOutlineSectionV5(BaseModel):
    """Stage A 无结构文档的 LLM 大纲 fallback 输出（chapter/section 两级）。"""

    model_config = ConfigDict(extra="ignore")

    ref: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    level: Literal[1, 2]
    parent_ref: str | None = None
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    evidence_page_numbers: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_page_range(self) -> KnowledgeOutlineSectionV5:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        if any(
            page < self.page_start or page > self.page_end
            for page in self.evidence_page_numbers
        ):
            raise ValueError("evidence pages must lie within the section range")
        return self


class KnowledgeOutlineV5(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root_title: str = Field(min_length=1, max_length=255)
    sections: list[KnowledgeOutlineSectionV5] = Field(default_factory=list)


class KnowledgeLeafV5(BaseModel):
    """Stage B 单个 section 内抽出的叶子知识点（v5，平铺、禁容器）。"""

    model_config = ConfigDict(extra="ignore")

    ref: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=1000)
    sources: list[KnowledgeSourceCandidate] = Field(min_length=1)


# 关系类型是展示用的语义标签，不是判分或掌握度依据。六类之外一律在流水线里
# 丢弃——不放进 Literal，否则模型给一个陌生类型就会让整个窗口重抽/失败。
RELATION_TYPES: tuple[str, ...] = (
    "prerequisite",
    "derives",
    "causes",
    "contrasts_with",
    "applies_to",
    "counterexample_of",
)


class KnowledgeRelationV5(BaseModel):
    """Stage B 单个 section 输出内的叶子关系（版本作用域，只连本次输出叶子）。

    字段刻意宽松：关系是可选装饰，任何一处畸形（缺 ref、confidence 写成
    "high"、evidence 是对象）都只能让这条关系被流水线丢弃，不能让整个窗口
    校验失败。真正的合法性判定在 KnowledgeBuildPipeline._collect_relations。
    """

    model_config = ConfigDict(extra="ignore")

    source_ref: str = ""
    target_ref: str = ""
    relation_type: str = ""
    confidence: float = -1.0
    evidence: str | None = None

    @field_validator("source_ref", "target_ref", "relation_type", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        return value if isinstance(value, str) else ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        # 无法解析的置信度记为越界哨兵值，交给流水线按"非法"丢弃
        if isinstance(value, bool) or value is None:
            return -1.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return -1.0
        return -1.0

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_evidence(cls, value: object) -> str | None:
        if value is None or isinstance(value, str):
            return value
        return None


class KnowledgeSectionExtractionV5(BaseModel):
    model_config = ConfigDict(extra="ignore")

    section_ref: str = Field(min_length=1, max_length=80)
    leaves: list[KnowledgeLeafV5] = Field(default_factory=list)
    relations: list[KnowledgeRelationV5] = Field(default_factory=list)

    @field_validator("relations", mode="before")
    @classmethod
    def _coerce_relations(cls, value: object) -> list:
        # 老 payload 没有 relations；模型偶尔给单个对象或字符串，按空/单元素处理
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, (dict, KnowledgeRelationV5))
        ]


class QuestionOptionCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1, max_length=500)


class QuestionKnowledgeMappingCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    knowledge_node_id: str
    relation_role: str = Field(min_length=1, max_length=50)
    weight: float = Field(gt=0, le=1)


class RubricCriterionCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    criterion_id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=500)
    max_points: float = Field(gt=0, le=100)
    acceptable_phrases: list[str] = Field(default_factory=list)


class ShortAnswerRubricCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_points: float = Field(gt=0, le=100)
    criteria: list[RubricCriterionCandidate] = Field(min_length=1)


class QuizQuestionCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_type: str
    stem: str = Field(min_length=1, max_length=2000)
    options: list[QuestionOptionCandidate] = Field(default_factory=list)
    answer_key_option_ids: list[str] = Field(default_factory=list)
    reference_answer: str | None = None
    rubric: ShortAnswerRubricCandidate | None = None
    explanation: str | None = None
    difficulty: str = Field(min_length=1, max_length=50)
    knowledge_mappings: list[QuestionKnowledgeMappingCandidate] = Field(min_length=1)
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_page_numbers: list[int] = Field(default_factory=list)


class QuizGenerationCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: list[QuizQuestionCandidate] = Field(min_length=1)


class ShortAnswerCriterionScoreCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    criterion_id: str = Field(min_length=1, max_length=50)
    awarded_points: float = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=500)


class ShortAnswerGradingCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: float = Field(ge=0, le=100)
    criterion_scores: list[ShortAnswerCriterionScoreCandidate] = Field(default_factory=list)
    feedback: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
