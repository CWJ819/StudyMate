from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T", bound=BaseModel)


class LLMRunSummary(BaseModel):
    model_name: str
    prompt_version: str
    provider: str


class LLMStructuredResult(BaseModel, Generic[T]):
    summary: LLMRunSummary
    data: T


class KnowledgeSourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_number: int = Field(ge=1)
    chunk_id: str | None = None
    evidence_type: str = "page_excerpt"


class KnowledgeNodeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    section_label: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    content: str | None = None
    sources: list[KnowledgeSourceCandidate] = Field(default_factory=list)
    children: list["KnowledgeNodeCandidate"] = Field(default_factory=list)


class KnowledgeRelationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str
    target_ref: str
    relation_type: str
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None


class KnowledgeFrameworkCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_title: str = Field(min_length=1, max_length=255)
    root_description: str | None = None
    nodes: list[KnowledgeNodeCandidate] = Field(default_factory=list)
    relations: list[KnowledgeRelationCandidate] = Field(default_factory=list)


class QuestionOptionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=50)
    text: str = Field(min_length=1, max_length=500)


class QuestionKnowledgeMappingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_node_id: str
    relation_role: str = Field(min_length=1, max_length=50)
    weight: float = Field(gt=0, le=1)


class RubricCriterionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=500)
    max_points: float = Field(gt=0, le=100)
    acceptable_phrases: list[str] = Field(default_factory=list)


class ShortAnswerRubricCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_points: float = Field(gt=0, le=100)
    criteria: list[RubricCriterionCandidate] = Field(min_length=1)


class QuizQuestionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    questions: list[QuizQuestionCandidate] = Field(min_length=1)


class ShortAnswerCriterionScoreCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1, max_length=50)
    awarded_points: float = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=500)


class ShortAnswerGradingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=100)
    criterion_scores: list[ShortAnswerCriterionScoreCandidate] = Field(default_factory=list)
    feedback: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
