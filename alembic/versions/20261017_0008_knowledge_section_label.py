"""add knowledge section labels

Revision ID: 20261017_0008
Revises: 20261017_0007
Create Date: 2026-10-17 21:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_0008"
down_revision = "20261017_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_node_versions",
        sa.Column("section_label", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_node_versions", "section_label")
