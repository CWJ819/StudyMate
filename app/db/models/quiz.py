from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("course_id", "content_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    answer_key_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rubric_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(50), nullable=False)
    source_metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    course: Mapped["Course"] = relationship(back_populates="questions")
    knowledge_mappings: Mapped[list["QuestionKnowledge"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    quiz_links: Mapped[list["QuizQuestion"]] = relationship(back_populates="question")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="question")


class QuestionKnowledge(Base):
    __tablename__ = "question_knowledge"
    __table_args__ = (UniqueConstraint("question_id", "node_version_id", "relation_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_node_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    relation_role: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)

    question: Mapped["Question"] = relationship(back_populates="knowledge_mappings")
    node_version: Mapped["KnowledgeNodeVersion"] = relationship()


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    framework_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_framework_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    settings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    course: Mapped["Course"] = relationship(back_populates="quizzes")
    framework_version: Mapped["KnowledgeFrameworkVersion"] = relationship()
    quiz_questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="QuizQuestion.ordinal",
    )
    submissions: Mapped[list["QuizSubmission"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    generation_runs: Mapped[list["QuestionGenerationRun"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "ordinal"),
        UniqueConstraint("quiz_id", "question_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    quiz_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    question_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    quiz: Mapped["Quiz"] = relationship(back_populates="quiz_questions")
    question: Mapped["Question"] = relationship(back_populates="quiz_links")


class QuizSubmission(Base):
    __tablename__ = "quiz_submissions"
    __table_args__ = (UniqueConstraint("quiz_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    quiz_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    quiz: Mapped["Quiz"] = relationship(back_populates="submissions")
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("quiz_id", "question_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quiz_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quiz_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_answer_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    grading_method: Mapped[str] = mapped_column(String(50), nullable=False)
    feedback_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    submission: Mapped["QuizSubmission"] = relationship(back_populates="attempts")
    question: Mapped["Question"] = relationship(back_populates="attempts")
    gap_evidence: Mapped[list["AttemptGapEvidence"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mastery_events: Mapped[list["MasteryEvent"]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class QuestionGenerationRun(Base):
    __tablename__ = "question_generation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    quiz_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    quiz: Mapped["Quiz"] = relationship(back_populates="generation_runs")
