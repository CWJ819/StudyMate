"""persist knowledge framework batch checkpoints"""

from alembic import op
import sqlalchemy as sa

revision = "20261020_0011"
down_revision = "20261020_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_build_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("framework_version_id", sa.String(length=36), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("candidate_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["framework_version_id"], ["knowledge_framework_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("framework_version_id", "batch_index"),
    )
    op.create_index("ix_knowledge_build_batches_framework_version_id", "knowledge_build_batches", ["framework_version_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_build_batches_framework_version_id", table_name="knowledge_build_batches")
    op.drop_table("knowledge_build_batches")
