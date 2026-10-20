from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class KnowledgeFrameworkVersion(Base):
    __tablename__ = "knowledge_framework_versions"
    __table_args__ = (UniqueConstraint("course_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    course: Mapped["Course"] = relationship(back_populates="framework_versions")
    node_versions: Mapped[list["KnowledgeNodeVersion"]] = relationship(
        back_populates="framework_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="KnowledgeNodeVersion.sort_order",
    )
    relations: Mapped[list["KnowledgeNodeRelation"]] = relationship(
        back_populates="framework_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeBuildBatch(Base):
    __tablename__ = "knowledge_build_batches"
    __table_args__ = (UniqueConstraint("framework_version_id", "batch_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    framework_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_framework_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    candidate_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (UniqueConstraint("course_id", "stable_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stable_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    course: Mapped["Course"] = relationship(back_populates="knowledge_nodes")
    versions: Mapped[list["KnowledgeNodeVersion"]] = relationship(back_populates="knowledge_node")


class KnowledgeNodeVersion(Base):
    __tablename__ = "knowledge_node_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    framework_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_framework_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_node_versions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    section_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    framework_version: Mapped["KnowledgeFrameworkVersion"] = relationship(back_populates="node_versions")
    knowledge_node: Mapped["KnowledgeNode"] = relationship(back_populates="versions")
    parent: Mapped["KnowledgeNodeVersion | None"] = relationship(
        remote_side=lambda: KnowledgeNodeVersion.id,
        back_populates="children",
    )
    children: Mapped[list["KnowledgeNodeVersion"]] = relationship(back_populates="parent")
    sources: Mapped[list["KnowledgeSource"]] = relationship(
        back_populates="node_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    outgoing_relations: Mapped[list["KnowledgeNodeRelation"]] = relationship(
        foreign_keys="KnowledgeNodeRelation.source_node_version_id",
        back_populates="source_node_version",
    )
    incoming_relations: Mapped[list["KnowledgeNodeRelation"]] = relationship(
        foreign_keys="KnowledgeNodeRelation.target_node_version_id",
        back_populates="target_node_version",
    )


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    node_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_node_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("document_chunks.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)

    node_version: Mapped["KnowledgeNodeVersion"] = relationship(back_populates="sources")
    document: Mapped["Document"] = relationship()
    chunk: Mapped["DocumentChunk | None"] = relationship()


class KnowledgeNodeRelation(Base):
    __tablename__ = "knowledge_node_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    framework_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_framework_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_node_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_node_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_node_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    framework_version: Mapped["KnowledgeFrameworkVersion"] = relationship(back_populates="relations")
    source_node_version: Mapped["KnowledgeNodeVersion"] = relationship(
        foreign_keys=[source_node_version_id],
        back_populates="outgoing_relations",
    )
    target_node_version: Mapped["KnowledgeNodeVersion"] = relationship(
        foreign_keys=[target_node_version_id],
        back_populates="incoming_relations",
    )
