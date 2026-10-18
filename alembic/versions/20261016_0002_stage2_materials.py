"""stage2 materials schema

Revision ID: 20261016_0002
Revises: 20261016_0001
Create Date: 2026-10-16 22:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261016_0002"
down_revision = "20261016_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(op.f("ix_documents_course_id"), "documents", ["course_id"], unique=False)

    op.create_table(
        "document_pages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(length=50), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "page_number"),
    )
    op.create_index(
        op.f("ix_document_pages_document_id"),
        "document_pages",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"),
        "document_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_document_pages_document_id"), table_name="document_pages")
    op.drop_table("document_pages")
    op.drop_index(op.f("ix_documents_course_id"), table_name="documents")
    op.drop_table("documents")
