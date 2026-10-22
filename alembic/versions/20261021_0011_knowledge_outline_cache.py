"""knowledge v5 outline cache

LLM 大纲缓存：让重建/续跑复用同一份章节划分，从而保持 section 缓存键稳定。

Revision ID: 20261021_0011
Revises: 20261021_0010
Create Date: 2026-10-21 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "20261021_0011"
down_revision = "20261021_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_outline_cache",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("provider_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_index(
        op.f("ix_knowledge_outline_cache_document_id"),
        "knowledge_outline_cache",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_outline_cache_document_id"),
        table_name="knowledge_outline_cache",
    )
    op.drop_table("knowledge_outline_cache")
