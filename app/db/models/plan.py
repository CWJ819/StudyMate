from datetime import date, datetime, UTC
from uuid import uuid4

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StudyPlan(Base):
    __tablename__ = "study_plans"
    __table_args__ = (UniqueConstraint("course_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    target_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    constraints_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    course: Mapped["Course"] = relationship(back_populates="study_plans")
    tasks: Mapped[list["StudyTask"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StudyTask.scheduled_date",
    )


class StudyTask(Base):
    __tablename__ = "study_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("study_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
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

    plan: Mapped["StudyPlan"] = relationship(back_populates="tasks")
    targets: Mapped[list["StudyTaskTarget"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class StudyTaskTarget(Base):
    __tablename__ = "study_task_targets"
    __table_args__ = (UniqueConstraint("task_id", "knowledge_node_id", "target_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("study_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_role: Mapped[str] = mapped_column(String(50), nullable=False)

    task: Mapped["StudyTask"] = relationship(back_populates="targets")
    knowledge_node: Mapped["KnowledgeNode"] = relationship()
