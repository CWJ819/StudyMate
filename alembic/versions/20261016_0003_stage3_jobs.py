"""stage3 jobs schema

Revision ID: 20261016_0003
Revises: 20261016_0002
Create Date: 2026-10-16 22:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_0003"
down_revision = "20261016_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_run_after"), "jobs", ["run_after"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_type"), "jobs", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_type"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_run_after"), table_name="jobs")
    op.drop_table("jobs")

