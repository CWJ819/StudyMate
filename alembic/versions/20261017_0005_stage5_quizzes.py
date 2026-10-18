"""stage5 quiz generation and grading schema

Revision ID: 20261017_0005
Revises: 20261016_0004
Create Date: 2026-10-17 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261017_0005"
down_revision = "20261016_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=True),
        sa.Column("answer_key_json", sa.JSON(), nullable=True),
        sa.Column("rubric_json", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.String(length=50), nullable=False),
        sa.Column("source_metadata_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "content_hash"),
    )
    op.create_index(op.f("ix_questions_course_id"), "questions", ["course_id"], unique=False)

    op.create_table(
        "question_knowledge",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("node_version_id", sa.String(length=36), nullable=False),
        sa.Column("relation_role", sa.String(length=50), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["node_version_id"], ["knowledge_node_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "node_version_id", "relation_role"),
    )
    op.create_index(
        op.f("ix_question_knowledge_node_version_id"),
        "question_knowledge",
        ["node_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_knowledge_question_id"),
        "question_knowledge",
        ["question_id"],
        unique=False,
    )

    op.create_table(
        "quizzes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("framework_version_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["framework_version_id"],
            ["knowledge_framework_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quizzes_course_id"), "quizzes", ["course_id"], unique=False)
    op.create_index(
        op.f("ix_quizzes_framework_version_id"),
        "quizzes",
        ["framework_version_id"],
        unique=False,
    )

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quiz_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question_snapshot_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quiz_id", "ordinal"),
        sa.UniqueConstraint("quiz_id", "question_id"),
    )
    op.create_index(
        op.f("ix_quiz_questions_question_id"),
        "quiz_questions",
        ["question_id"],
        unique=False,
    )
    op.create_index(op.f("ix_quiz_questions_quiz_id"), "quiz_questions", ["quiz_id"], unique=False)

    op.create_table(
        "quiz_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quiz_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quiz_id", "idempotency_key"),
    )
    op.create_index(
        op.f("ix_quiz_submissions_quiz_id"),
        "quiz_submissions",
        ["quiz_id"],
        unique=False,
    )

    op.create_table(
        "attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("quiz_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("submitted_answer_json", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("grading_method", sa.String(length=50), nullable=False),
        sa.Column("feedback_json", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["quiz_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quiz_id", "question_id"),
    )
    op.create_index(op.f("ix_attempts_question_id"), "attempts", ["question_id"], unique=False)
    op.create_index(op.f("ix_attempts_quiz_id"), "attempts", ["quiz_id"], unique=False)
    op.create_index(op.f("ix_attempts_submission_id"), "attempts", ["submission_id"], unique=False)

    op.create_table(
        "question_generation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quiz_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("input_summary_json", sa.JSON(), nullable=False),
        sa.Column("output_summary_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_question_generation_runs_quiz_id"),
        "question_generation_runs",
        ["quiz_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_question_generation_runs_quiz_id"),
        table_name="question_generation_runs",
    )
    op.drop_table("question_generation_runs")
    op.drop_index(op.f("ix_attempts_submission_id"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_quiz_id"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_question_id"), table_name="attempts")
    op.drop_table("attempts")
    op.drop_index(op.f("ix_quiz_submissions_quiz_id"), table_name="quiz_submissions")
    op.drop_table("quiz_submissions")
    op.drop_index(op.f("ix_quiz_questions_quiz_id"), table_name="quiz_questions")
    op.drop_index(op.f("ix_quiz_questions_question_id"), table_name="quiz_questions")
    op.drop_table("quiz_questions")
    op.drop_index(op.f("ix_quizzes_framework_version_id"), table_name="quizzes")
    op.drop_index(op.f("ix_quizzes_course_id"), table_name="quizzes")
    op.drop_table("quizzes")
    op.drop_index(
        op.f("ix_question_knowledge_question_id"),
        table_name="question_knowledge",
    )
    op.drop_index(
        op.f("ix_question_knowledge_node_version_id"),
        table_name="question_knowledge",
    )
    op.drop_table("question_knowledge")
    op.drop_index(op.f("ix_questions_course_id"), table_name="questions")
    op.drop_table("questions")
