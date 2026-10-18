"""stage4 knowledge schema

Revision ID: 20261016_0004
Revises: 20261016_0003
Create Date: 2026-10-16 23:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_0004"
down_revision = "20261016_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_framework_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "version_number"),
    )
    op.create_index(
        op.f("ix_knowledge_framework_versions_course_id"),
        "knowledge_framework_versions",
        ["course_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("stable_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "stable_key"),
    )
    op.create_index(
        op.f("ix_knowledge_nodes_course_id"),
        "knowledge_nodes",
        ["course_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_node_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("framework_version_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("is_leaf", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["framework_version_id"],
            ["knowledge_framework_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["knowledge_node_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_node_versions_framework_version_id"),
        "knowledge_node_versions",
        ["framework_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_node_versions_knowledge_node_id"),
        "knowledge_node_versions",
        ["knowledge_node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_node_versions_parent_id"),
        "knowledge_node_versions",
        ["parent_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("node_version_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["document_chunks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["node_version_id"], ["knowledge_node_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_sources_chunk_id"),
        "knowledge_sources",
        ["chunk_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_sources_document_id"),
        "knowledge_sources",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_sources_node_version_id"),
        "knowledge_sources",
        ["node_version_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_node_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("framework_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_node_version_id", sa.String(length=36), nullable=False),
        sa.Column("target_node_version_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["framework_version_id"],
            ["knowledge_framework_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_version_id"],
            ["knowledge_node_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_version_id"],
            ["knowledge_node_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_node_relations_framework_version_id"),
        "knowledge_node_relations",
        ["framework_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_node_relations_source_node_version_id"),
        "knowledge_node_relations",
        ["source_node_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_node_relations_target_node_version_id"),
        "knowledge_node_relations",
        ["target_node_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_node_relations_target_node_version_id"),
        table_name="knowledge_node_relations",
    )
    op.drop_index(
        op.f("ix_knowledge_node_relations_source_node_version_id"),
        table_name="knowledge_node_relations",
    )
    op.drop_index(
        op.f("ix_knowledge_node_relations_framework_version_id"),
        table_name="knowledge_node_relations",
    )
    op.drop_table("knowledge_node_relations")
    op.drop_index(op.f("ix_knowledge_sources_node_version_id"), table_name="knowledge_sources")
    op.drop_index(op.f("ix_knowledge_sources_document_id"), table_name="knowledge_sources")
    op.drop_index(op.f("ix_knowledge_sources_chunk_id"), table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
    op.drop_index(
        op.f("ix_knowledge_node_versions_parent_id"),
        table_name="knowledge_node_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_node_versions_knowledge_node_id"),
        table_name="knowledge_node_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_node_versions_framework_version_id"),
        table_name="knowledge_node_versions",
    )
    op.drop_table("knowledge_node_versions")
    op.drop_index(op.f("ix_knowledge_nodes_course_id"), table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
    op.drop_index(
        op.f("ix_knowledge_framework_versions_course_id"),
        table_name="knowledge_framework_versions",
    )
    op.drop_table("knowledge_framework_versions")
