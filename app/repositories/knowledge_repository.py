from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.course import Course
from app.db.models.document import Document, DocumentChunk, DocumentPage
from app.db.models.knowledge import (
    KnowledgeFrameworkVersion,
    KnowledgeNode,
    KnowledgeNodeRelation,
    KnowledgeNodeVersion,
    KnowledgeSource,
)


class KnowledgeRepository:
    def next_version_number(self, session: Session, course_id: str) -> int:
        current = session.scalar(
            select(func.max(KnowledgeFrameworkVersion.version_number)).where(
                KnowledgeFrameworkVersion.course_id == course_id
            )
        )
        return int(current or 0) + 1

    def create_framework_version(
        self,
        session: Session,
        *,
        course_id: str,
        version_number: int,
        status: str,
    ) -> KnowledgeFrameworkVersion:
        version = KnowledgeFrameworkVersion(
            course_id=course_id,
            version_number=version_number,
            status=status,
        )
        session.add(version)
        session.flush()
        session.refresh(version)
        return version

    def get_framework_version(
        self, session: Session, framework_version_id: str
    ) -> KnowledgeFrameworkVersion | None:
        statement = (
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.id == framework_version_id)
            .options(
                selectinload(KnowledgeFrameworkVersion.node_versions).selectinload(
                    KnowledgeNodeVersion.sources
                ),
                selectinload(KnowledgeFrameworkVersion.relations),
            )
        )
        return session.scalar(statement)

    def list_framework_versions(
        self, session: Session, course_id: str
    ) -> list[KnowledgeFrameworkVersion]:
        statement = (
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .order_by(KnowledgeFrameworkVersion.version_number.desc())
        )
        return list(session.scalars(statement))

    def get_active_framework(
        self, session: Session, course_id: str
    ) -> KnowledgeFrameworkVersion | None:
        statement = (
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .where(KnowledgeFrameworkVersion.status == "active")
            .options(
                selectinload(KnowledgeFrameworkVersion.node_versions).selectinload(
                    KnowledgeNodeVersion.sources
                ),
                selectinload(KnowledgeFrameworkVersion.relations),
            )
            .order_by(KnowledgeFrameworkVersion.version_number.desc())
            .limit(1)
        )
        return session.scalar(statement)

    def get_or_create_node(
        self, session: Session, *, course_id: str, stable_key: str
    ) -> KnowledgeNode:
        existing = session.scalar(
            select(KnowledgeNode)
            .where(KnowledgeNode.course_id == course_id)
            .where(KnowledgeNode.stable_key == stable_key)
        )
        if existing is not None:
            return existing
        node = KnowledgeNode(course_id=course_id, stable_key=stable_key)
        session.add(node)
        session.flush()
        session.refresh(node)
        return node

    def add_node_version(
        self,
        session: Session,
        *,
        framework_version_id: str,
        knowledge_node_id: str,
        parent_id: str | None,
        title: str,
        section_label: str | None,
        content: str | None,
        level: int,
        is_leaf: bool,
        sort_order: int,
    ) -> KnowledgeNodeVersion:
        node_version = KnowledgeNodeVersion(
            framework_version_id=framework_version_id,
            knowledge_node_id=knowledge_node_id,
            parent_id=parent_id,
            title=title,
            section_label=section_label,
            content=content,
            level=level,
            is_leaf=is_leaf,
            sort_order=sort_order,
        )
        session.add(node_version)
        session.flush()
        session.refresh(node_version)
        return node_version

    def add_source(
        self,
        session: Session,
        *,
        node_version_id: str,
        document_id: str,
        page_number: int,
        chunk_id: str | None,
        evidence_type: str,
    ) -> KnowledgeSource:
        source = KnowledgeSource(
            node_version_id=node_version_id,
            document_id=document_id,
            page_number=page_number,
            chunk_id=chunk_id,
            evidence_type=evidence_type,
        )
        session.add(source)
        session.flush()
        return source

    def add_relation(
        self,
        session: Session,
        *,
        framework_version_id: str,
        source_node_version_id: str,
        target_node_version_id: str,
        relation_type: str,
        confidence: float,
        evidence: str | None,
    ) -> KnowledgeNodeRelation:
        relation = KnowledgeNodeRelation(
            framework_version_id=framework_version_id,
            source_node_version_id=source_node_version_id,
            target_node_version_id=target_node_version_id,
            relation_type=relation_type,
            confidence=confidence,
            evidence=evidence,
        )
        session.add(relation)
        session.flush()
        return relation

    def deactivate_active_versions(self, session: Session, course_id: str) -> None:
        now = datetime.now(UTC)
        for version in session.scalars(
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .where(KnowledgeFrameworkVersion.status == "active")
        ):
            version.status = "inactive"
            version.activated_at = version.activated_at or now

    def get_active_node_version(
        self, session: Session, *, course_id: str, knowledge_node_id: str
    ) -> KnowledgeNodeVersion | None:
        active_version = self.get_active_framework(session, course_id)
        if active_version is None:
            return None
        statement = (
            select(KnowledgeNodeVersion)
            .where(KnowledgeNodeVersion.framework_version_id == active_version.id)
            .where(KnowledgeNodeVersion.knowledge_node_id == knowledge_node_id)
            .options(
                selectinload(KnowledgeNodeVersion.sources),
                selectinload(KnowledgeNodeVersion.outgoing_relations),
                selectinload(KnowledgeNodeVersion.incoming_relations),
            )
        )
        return session.scalar(statement)

    def get_documents_for_framework_build(self, session: Session, course_id: str) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.course_id == course_id)
            .where(Document.status.in_(["completed", "completed_with_warnings"]))
            .options(selectinload(Document.pages), selectinload(Document.chunks))
            .order_by(Document.created_at.asc())
        )
        return list(session.scalars(statement))

    def document_page_exists(
        self, session: Session, *, document_id: str, page_number: int
    ) -> bool:
        return (
            session.scalar(
                select(DocumentPage.id)
                .where(DocumentPage.document_id == document_id)
                .where(DocumentPage.page_number == page_number)
                .limit(1)
            )
            is not None
        )

    def chunk_belongs_to_document(
        self, session: Session, *, chunk_id: str, document_id: str
    ) -> bool:
        return (
            session.scalar(
                select(DocumentChunk.id)
                .where(DocumentChunk.id == chunk_id)
                .where(DocumentChunk.document_id == document_id)
                .limit(1)
            )
            is not None
        )

    def is_document_referenced_by_knowledge(self, session: Session, document_id: str) -> bool:
        return (
            session.scalar(
                select(KnowledgeSource.id)
                .where(KnowledgeSource.document_id == document_id)
                .limit(1)
            )
            is not None
        )

    def get_course(self, session: Session, course_id: str) -> Course | None:
        return session.get(Course, course_id)
