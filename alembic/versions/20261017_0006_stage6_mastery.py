"""stage6 diagnosis and mastery schema

Revision ID: 20261017_0006
Revises: 20261017_0005
Create Date: 2026-10-17 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_0006"
down_revision = "20261017_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("node_version_id", sa.String(length=36), nullable=False),
        sa.Column("gap_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["node_version_id"],
            ["knowledge_node_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "node_version_id", "gap_type"),
    )
    op.create_index(op.f("ix_knowledge_gaps_course_id"), "knowledge_gaps", ["course_id"])
    op.create_index(
        op.f("ix_knowledge_gaps_node_version_id"),
        "knowledge_gaps",
        ["node_version_id"],
    )

    op.create_table(
        "student_gap_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("mastery_estimate", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_node_id"],
            ["knowledge_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "knowledge_node_id"),
    )
    op.create_index(
        op.f("ix_student_gap_states_course_id"),
        "student_gap_states",
        ["course_id"],
    )
    op.create_index(
        op.f("ix_student_gap_states_knowledge_node_id"),
        "student_gap_states",
        ["knowledge_node_id"],
    )

    op.create_table(
        "review_strategy_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("selected_targets_json", sa.JSON(), nullable=False),
        sa.Column("strategy_version", sa.String(length=100), nullable=False),
        sa.Column("rationale_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_review_strategy_logs_course_id"),
        "review_strategy_logs",
        ["course_id"],
    )

    op.create_table(
        "attempt_gap_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("gap_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["gap_id"], ["knowledge_gaps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "gap_id"),
    )
    op.create_index(
        op.f("ix_attempt_gap_evidence_attempt_id"),
        "attempt_gap_evidence",
        ["attempt_id"],
    )
    op.create_index(
        op.f("ix_attempt_gap_evidence_gap_id"),
        "attempt_gap_evidence",
        ["gap_id"],
    )

    op.create_table(
        "mastery_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("delta_alpha", sa.Float(), nullable=False),
        sa.Column("delta_beta", sa.Float(), nullable=False),
        sa.Column("old_estimate", sa.Float(), nullable=False),
        sa.Column("new_estimate", sa.Float(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["state_id"], ["student_gap_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_id", "attempt_id"),
    )
    op.create_index(op.f("ix_mastery_events_attempt_id"), "mastery_events", ["attempt_id"])
    op.create_index(op.f("ix_mastery_events_state_id"), "mastery_events", ["state_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_mastery_events_state_id"), table_name="mastery_events")
    op.drop_index(op.f("ix_mastery_events_attempt_id"), table_name="mastery_events")
    op.drop_table("mastery_events")
    op.drop_index(op.f("ix_attempt_gap_evidence_gap_id"), table_name="attempt_gap_evidence")
    op.drop_index(op.f("ix_attempt_gap_evidence_attempt_id"), table_name="attempt_gap_evidence")
    op.drop_table("attempt_gap_evidence")
    op.drop_index(op.f("ix_review_strategy_logs_course_id"), table_name="review_strategy_logs")
    op.drop_table("review_strategy_logs")
    op.drop_index(
        op.f("ix_student_gap_states_knowledge_node_id"),
        table_name="student_gap_states",
    )
    op.drop_index(op.f("ix_student_gap_states_course_id"), table_name="student_gap_states")
    op.drop_table("student_gap_states")
    op.drop_index(op.f("ix_knowledge_gaps_node_version_id"), table_name="knowledge_gaps")
    op.drop_index(op.f("ix_knowledge_gaps_course_id"), table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
