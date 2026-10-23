from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


QUESTION_TYPE_SINGLE_CHOICE = "single_choice"
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_SHORT_ANSWER = "short_answer"
QUESTION_TYPES = {
    QUESTION_TYPE_SINGLE_CHOICE,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_SHORT_ANSWER,
}

QUIZ_STATUS_BUILDING = "building"
QUIZ_STATUS_OPEN = "open"
QUIZ_STATUS_SUBMITTED = "submitted"
QUIZ_STATUS_FAILED = "failed"


class QuizGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_node_ids: list[str] = Field(default_factory=list, max_length=50)
    question_count: int = Field(default=10, ge=1, le=20)
    question_types: list[str] = Field(
        default_factory=lambda: [
            QUESTION_TYPE_SINGLE_CHOICE,
            QUESTION_TYPE_MULTIPLE_CHOICE,
            QUESTION_TYPE_SHORT_ANSWER,
        ],
        min_length=1,
        max_length=3,
    )
    difficulty: str = Field(default="low", min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_question_types(self) -> "QuizGenerateRequest":
        normalized = list(dict.fromkeys(self.question_types))
        invalid = [question_type for question_type in normalized if question_type not in QUESTION_TYPES]
        if invalid:
            raise ValueError(f"Unsupported question types: {', '.join(sorted(invalid))}")
        self.question_types = normalized
        return self


class QuizGenerateResponse(BaseModel):
    quiz_id: str
    job_id: str
    status: str


class QuizQuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class QuestionRubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    description: str
    max_points: float = Field(gt=0)
    acceptable_phrases: list[str] = Field(default_factory=list)


class QuestionRubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_points: float = Field(gt=0)
    criteria: list[QuestionRubricCriterion] = Field(min_length=1)


def normalize_rubric(rubric: QuestionRubric) -> QuestionRubric:
    """Keep the rubric total and its criteria in the same unit.

    LLM candidates occasionally report a plausible total that does not match
    the criterion breakdown.  The criteria are the grading source of truth, so
    the stored total is aligned to their sum instead of rejecting an otherwise
    usable generated question.
    """
    criterion_total = sum(float(criterion.max_points) for criterion in rubric.criteria)
    if abs(float(rubric.max_points) - criterion_total) <= 1e-6:
        return rubric
    return rubric.model_copy(update={"max_points": criterion_total})


class QuestionKnowledgeMappingSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_node_id: str
    node_version_id: str
    title: str
    relation_role: str
    weight: float


class QuizQuestionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_type: str
    stem: str
    options: list[QuizQuestionOption] = Field(default_factory=list)
    answer_key_option_ids: list[str] = Field(default_factory=list)
    reference_answer: str | None = None
    rubric: QuestionRubric | None = None
    explanation: str | None = None
    difficulty: str
    max_score: float
    knowledge_mappings: list[QuestionKnowledgeMappingSnapshot]
    source_metadata: dict = Field(default_factory=dict)


class QuizQuestionResponse(BaseModel):
    question_id: str
    ordinal: int
    question_type: str
    stem: str
    options: list[QuizQuestionOption]
    difficulty: str
    max_score: float


class QuizDetailResponse(BaseModel):
    quiz_id: str
    course_id: str
    framework_version_id: str
    status: str
    created_at: datetime
    questions: list[QuizQuestionResponse]


class QuizAnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    selected_option_ids: list[str] | None = None
    text: str | None = None


class QuizSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    answers: list[QuizAnswerInput] = Field(min_length=1, max_length=50)


class QuizQuestionResultResponse(BaseModel):
    question_id: str
    score: float
    max_score: float
    grading_method: str
    correct: bool | None = None
    feedback_text: str | None = None


class QuizSubmitResponse(BaseModel):
    submission_id: str
    quiz_id: str
    status: str
    total_score: float
    max_score: float
    question_results: list[QuizQuestionResultResponse]
