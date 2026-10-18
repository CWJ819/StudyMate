"""rename knowledge node description to content

Revision ID: 20261018_0009
Revises: 20261017_0008
Create Date: 2026-10-18 00:00:00
"""

from __future__ import annotations

from alembic import op


revision = "20261018_0009"
down_revision = "20261017_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_node_versions",
        "description",
        new_column_name="content",
    )


def downgrade() -> None:
    op.alter_column(
        "knowledge_node_versions",
        "content",
        new_column_name="description",
    )
