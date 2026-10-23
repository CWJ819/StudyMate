"""knowledge v5 cross-document alignment and alias locks

Revision ID: 20261021_0012
Revises: 20261021_0011
Create Date: 2026-10-23 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "20261021_0012"
down_revision = "20261021_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_node_versions",
        sa.Column("aliases", sa.JSON(), nullable=True),
    )
    op.create_table(
        "knowledge_merge_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("framework_version_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_title", sa.String(length=255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("members", sa.JSON(), nullable=False),
        sa.Column("distinct_documents", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["framework_version_id"],
            ["knowledge_framework_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_merge_decisions_framework_version_id"),
        "knowledge_merge_decisions",
        ["framework_version_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_alias_locks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("title_a", sa.String(length=255), nullable=False),
        sa.Column("title_b", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "title_a", "title_b"),
    )
    op.create_index(
        op.f("ix_knowledge_alias_locks_course_id"),
        "knowledge_alias_locks",
        ["course_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_alias_locks_course_id"),
        table_name="knowledge_alias_locks",
    )
    op.drop_table("knowledge_alias_locks")
    op.drop_index(
        op.f("ix_knowledge_merge_decisions_framework_version_id"),
        table_name="knowledge_merge_decisions",
    )
    op.drop_table("knowledge_merge_decisions")
    op.drop_column("knowledge_node_versions", "aliases")
