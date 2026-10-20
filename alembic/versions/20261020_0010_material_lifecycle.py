"""add material lifecycle and framework input snapshots"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261020_0010"
down_revision = "20261018_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("material_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("documents", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_framework_versions", sa.Column("input_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("knowledge_framework_versions", sa.Column("input_document_ids", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("knowledge_framework_versions", "input_document_ids")
    op.drop_column("knowledge_framework_versions", "input_revision")
    op.drop_column("documents", "archived_at")
    op.drop_column("courses", "material_revision")
