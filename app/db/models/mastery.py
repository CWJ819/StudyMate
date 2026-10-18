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


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    __table_args__ = (UniqueConstraint("course_id", "node_version_id", "gap_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_node_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    gap_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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

    course: Mapped["Course"] = relationship(back_populates="knowledge_gaps")
    node_version: Mapped["KnowledgeNodeVersion"] = relationship()
    evidence: Mapped[list["AttemptGapEvidence"]] = relationship(
        back_populates="gap",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AttemptGapEvidence(Base):
    __tablename__ = "attempt_gap_evidence"
    __table_args__ = (UniqueConstraint("attempt_id", "gap_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    attempt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gap_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_gaps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    attempt: Mapped["Attempt"] = relationship(back_populates="gap_evidence")
    gap: Mapped["KnowledgeGap"] = relationship(back_populates="evidence")


class StudentGapState(Base):
    __tablename__ = "student_gap_states"
    __table_args__ = (UniqueConstraint("course_id", "knowledge_node_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alpha: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    beta: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    mastery_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    course: Mapped["Course"] = relationship(back_populates="student_gap_states")
    knowledge_node: Mapped["KnowledgeNode"] = relationship()
    mastery_events: Mapped[list["MasteryEvent"]] = relationship(
        back_populates="state",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MasteryEvent(Base):
    __tablename__ = "mastery_events"
    __table_args__ = (UniqueConstraint("state_id", "attempt_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    state_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("student_gap_states.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    delta_alpha: Mapped[float] = mapped_column(Float, nullable=False)
    delta_beta: Mapped[float] = mapped_column(Float, nullable=False)
    old_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    new_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    state: Mapped["StudentGapState"] = relationship(back_populates="mastery_events")
    attempt: Mapped["Attempt"] = relationship(back_populates="mastery_events")


class ReviewStrategyLog(Base):
    __tablename__ = "review_strategy_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    selected_targets_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    rationale_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    course: Mapped["Course"] = relationship(back_populates="review_strategy_logs")
