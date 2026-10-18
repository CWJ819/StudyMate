"""stage7 study plan schema

Revision ID: 20261017_0007
Revises: 20261017_0006
Create Date: 2026-10-17 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_0007"
down_revision = "20261017_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=False),
        sa.Column("target_score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "version_number"),
    )
    op.create_index(op.f("ix_study_plans_course_id"), "study_plans", ["course_id"])

    op.create_table(
        "study_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["study_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_study_tasks_plan_id"), "study_tasks", ["plan_id"])
    op.create_index(op.f("ix_study_tasks_scheduled_date"), "study_tasks", ["scheduled_date"])

    op.create_table(
        "study_task_targets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("target_role", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["study_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "knowledge_node_id", "target_role"),
    )
    op.create_index(
        op.f("ix_study_task_targets_knowledge_node_id"),
        "study_task_targets",
        ["knowledge_node_id"],
    )
    op.create_index(op.f("ix_study_task_targets_task_id"), "study_task_targets", ["task_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_study_task_targets_task_id"), table_name="study_task_targets")
    op.drop_index(
        op.f("ix_study_task_targets_knowledge_node_id"),
        table_name="study_task_targets",
    )
    op.drop_table("study_task_targets")
    op.drop_index(op.f("ix_study_tasks_scheduled_date"), table_name="study_tasks")
    op.drop_index(op.f("ix_study_tasks_plan_id"), table_name="study_tasks")
    op.drop_table("study_tasks")
    op.drop_index(op.f("ix_study_plans_course_id"), table_name="study_plans")
    op.drop_table("study_plans")
