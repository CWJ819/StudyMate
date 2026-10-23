from datetime import UTC, datetime
from uuid import uuid4

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
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
    # v5 起记录构建器版本与课程材料指纹；旧版本两列为 NULL（legacy）。
    builder_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    # 跨文档对齐时被并进来的其它标题；canonical 标题仍是 title。
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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


class KnowledgeSectionCache(Base):
    """v5 流水线的 section/window 级断点缓存。

    只有通过 Pydantic 校验的抽取结果才入缓存；构建失败后重新触发可
    直接复用，跳过已完成的 LLM 调用。独立于构建事务提交。
    """

    __tablename__ = "knowledge_section_cache"
    __table_args__ = (UniqueConstraint("cache_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class KnowledgeOutlineCache(Base):
    """v5 Stage A 的 LLM 大纲缓存。

    大纲由模型生成，每次可能有细微差异；不缓存就会让 section 缓存键
    （含 section 路径与页码区间）失效，重建/续跑退化为全量重抽。
    缓存键包含解析器版本、文档内容指纹、模型与 provider。
    """

    __tablename__ = "knowledge_outline_cache"
    __table_args__ = (UniqueConstraint("cache_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class KnowledgeMergeDecision(Base):
    """Stage C 跨 section 对齐时发生的一次合并，只记录真正合并的簇。"""

    __tablename__ = "knowledge_merge_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    framework_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_framework_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_title: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    members: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    distinct_documents: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class KnowledgeAliasLock(Base):
    """用户显式锁定的标题对：自动对齐时不得把这两片叶子并成一个。"""

    __tablename__ = "knowledge_alias_locks"
    __table_args__ = (UniqueConstraint("course_id", "title_a", "title_b"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title_a: Mapped[str] = mapped_column(String(255), nullable=False)
    title_b: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
