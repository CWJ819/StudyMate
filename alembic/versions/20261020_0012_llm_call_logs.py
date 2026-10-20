"""add metadata-only LLM call logs"""

from alembic import op
import sqlalchemy as sa

revision = "20261020_0012"
down_revision = "20261020_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("input_summary_json", sa.JSON(), nullable=False),
        sa.Column("output_summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_call_logs_course_id", "llm_call_logs", ["course_id"])
    op.create_index("ix_llm_call_logs_job_id", "llm_call_logs", ["job_id"])
    op.create_index("ix_llm_call_logs_operation", "llm_call_logs", ["operation"])
    op.create_index("ix_llm_call_logs_status", "llm_call_logs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_status", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_operation", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_job_id", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_course_id", table_name="llm_call_logs")
    op.drop_table("llm_call_logs")
