"""knowledge v5 build foundation

Jobs phase progress columns, llm_calls observability table,
knowledge_section_cache checkpoint table, and framework version
builder metadata (builder_version / source_fingerprint).

Revision ID: 20261021_0010
Revises: 20261018_0009
Create Date: 2026-10-21 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "20261021_0010"
down_revision = "20261018_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("phase", sa.String(length=50), nullable=True))
    op.add_column("jobs", sa.Column("completed_units", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("total_units", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("message", sa.String(length=500), nullable=True))

    op.add_column(
        "knowledge_framework_versions",
        sa.Column("builder_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "knowledge_framework_versions",
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_chars", sa.Integer(), nullable=True),
        sa.Column("output_chars", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_calls_job_id"), "llm_calls", ["job_id"], unique=False)

    op.create_table(
        "knowledge_section_cache",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("provider_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_section_cache")
    op.drop_index(op.f("ix_llm_calls_job_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_column("knowledge_framework_versions", "source_fingerprint")
    op.drop_column("knowledge_framework_versions", "builder_version")
    op.drop_column("jobs", "message")
    op.drop_column("jobs", "total_units")
    op.drop_column("jobs", "completed_units")
    op.drop_column("jobs", "phase")
