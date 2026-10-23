from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.course import Course
from app.db.models.document import Document, DocumentChunk, DocumentPage
from app.db.models.knowledge import (
    KnowledgeAliasLock,
    KnowledgeFrameworkVersion,
    KnowledgeMergeDecision,
    KnowledgeNode,
    KnowledgeNodeRelation,
    KnowledgeNodeVersion,
    KnowledgeOutlineCache,
    KnowledgeSectionCache,
    KnowledgeSource,
)
from app.db.models.job import Job
from app.db.models.quiz import QuestionKnowledge


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

    # ------------------------------------------------------------------
    # 评分读取时计算用的聚合查询（不写库、不缓存）
    # ------------------------------------------------------------------

    def count_source_pages_by_node(
        self, session: Session, *, framework_version_id: str
    ) -> dict[str, int]:
        """每片叶子 distinct 的来源页数（document_id + page_number 去重）。"""
        rows = session.execute(
            select(
                KnowledgeSource.node_version_id,
                KnowledgeSource.document_id,
                KnowledgeSource.page_number,
            )
            .join(
                KnowledgeNodeVersion,
                KnowledgeNodeVersion.id == KnowledgeSource.node_version_id,
            )
            .where(KnowledgeNodeVersion.framework_version_id == framework_version_id)
        )
        pages: dict[str, set[tuple[str, int]]] = {}
        for node_version_id, document_id, page_number in rows:
            pages.setdefault(node_version_id, set()).add((document_id, page_number))
        return {node_version_id: len(values) for node_version_id, values in pages.items()}

    def count_source_documents_by_node(
        self, session: Session, *, framework_version_id: str
    ) -> dict[str, int]:
        """每片叶子 distinct 的来源文档数（跨文档覆盖分量 X）。"""
        rows = session.execute(
            select(
                KnowledgeSource.node_version_id,
                func.count(func.distinct(KnowledgeSource.document_id)),
            )
            .join(
                KnowledgeNodeVersion,
                KnowledgeNodeVersion.id == KnowledgeSource.node_version_id,
            )
            .where(KnowledgeNodeVersion.framework_version_id == framework_version_id)
            .group_by(KnowledgeSource.node_version_id)
        )
        return {node_version_id: int(count) for node_version_id, count in rows}

    def count_question_mappings_by_node(
        self, session: Session, *, framework_version_id: str
    ) -> dict[str, int]:
        """每片叶子映射到的题目数（同一题多角色只算一次）。"""
        rows = session.execute(
            select(
                QuestionKnowledge.node_version_id,
                func.count(func.distinct(QuestionKnowledge.question_id)),
            )
            .join(
                KnowledgeNodeVersion,
                KnowledgeNodeVersion.id == QuestionKnowledge.node_version_id,
            )
            .where(KnowledgeNodeVersion.framework_version_id == framework_version_id)
            .group_by(QuestionKnowledge.node_version_id)
        )
        return {node_version_id: int(count) for node_version_id, count in rows}

    def list_version_relations(
        self, session: Session, *, framework_version_id: str
    ) -> list[tuple[str, str, str]]:
        """active 版本的关系边 (source_node_version_id, target_node_version_id, type)。"""
        rows = session.execute(
            select(
                KnowledgeNodeRelation.source_node_version_id,
                KnowledgeNodeRelation.target_node_version_id,
                KnowledgeNodeRelation.relation_type,
            ).where(KnowledgeNodeRelation.framework_version_id == framework_version_id)
        )
        return [(source, target, relation_type) for source, target, relation_type in rows]

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

    def find_node_by_stable_key(
        self, session: Session, *, course_id: str, stable_key: str
    ) -> KnowledgeNode | None:
        return session.scalar(
            select(KnowledgeNode)
            .where(KnowledgeNode.course_id == course_id)
            .where(KnowledgeNode.stable_key == stable_key)
        )

    def update_node_stable_key(
        self, session: Session, *, knowledge_node: KnowledgeNode, stable_key: str
    ) -> None:
        knowledge_node.stable_key = stable_key
        session.flush()

    def get_building_framework_version(
        self, session: Session, course_id: str
    ) -> KnowledgeFrameworkVersion | None:
        return session.scalar(
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .where(KnowledgeFrameworkVersion.status == "building")
            .order_by(KnowledgeFrameworkVersion.version_number.desc())
            .limit(1)
        )

    def has_pending_build_job(
        self, session: Session, *, framework_version_id: str
    ) -> bool:
        return (
            session.scalar(
                select(Job.id)
                .where(Job.type == "knowledge_framework.build")
                .where(Job.status.in_(["queued", "running", "retry_wait"]))
                .where(
                    func.json_extract(Job.payload_json, "$.framework_version_id")
                    == framework_version_id
                )
                .limit(1)
            )
            is not None
        )

    def get_section_cache_payloads(
        self, session: Session, *, cache_keys: list[str]
    ) -> dict[str, dict]:
        if not cache_keys:
            return {}
        rows = session.scalars(
            select(KnowledgeSectionCache).where(
                KnowledgeSectionCache.cache_key.in_(cache_keys)
            )
        )
        return {row.cache_key: row.payload_json for row in rows}

    def add_section_cache_entry(
        self,
        session: Session,
        *,
        cache_key: str,
        content_hash: str,
        prompt_version: str,
        model_name: str,
        provider_hash: str,
        payload_json: dict,
    ) -> None:
        existing = session.scalar(
            select(KnowledgeSectionCache.id).where(
                KnowledgeSectionCache.cache_key == cache_key
            )
        )
        if existing is not None:
            return
        session.add(
            KnowledgeSectionCache(
                cache_key=cache_key,
                content_hash=content_hash,
                prompt_version=prompt_version,
                model_name=model_name,
                provider_hash=provider_hash,
                payload_json=payload_json,
            )
        )
        session.flush()

    def get_outline_cache_payload(
        self, session: Session, *, cache_key: str
    ) -> dict | None:
        return session.scalar(
            select(KnowledgeOutlineCache.payload_json).where(
                KnowledgeOutlineCache.cache_key == cache_key
            )
        )

    def add_outline_cache_entry(
        self,
        session: Session,
        *,
        cache_key: str,
        document_id: str,
        content_hash: str,
        parser_version: str,
        prompt_version: str,
        model_name: str,
        provider_hash: str,
        payload_json: dict,
    ) -> None:
        existing = session.scalar(
            select(KnowledgeOutlineCache.id).where(
                KnowledgeOutlineCache.cache_key == cache_key
            )
        )
        if existing is not None:
            return
        session.add(
            KnowledgeOutlineCache(
                cache_key=cache_key,
                document_id=document_id,
                content_hash=content_hash,
                parser_version=parser_version,
                prompt_version=prompt_version,
                model_name=model_name,
                provider_hash=provider_hash,
                payload_json=payload_json,
            )
        )
        session.flush()

    def add_merge_decision(
        self,
        session: Session,
        *,
        framework_version_id: str,
        canonical_title: str,
        aliases: list[str],
        members: list[str],
        distinct_documents: int,
        method: str,
        similarity: float | None,
    ) -> KnowledgeMergeDecision:
        decision = KnowledgeMergeDecision(
            framework_version_id=framework_version_id,
            canonical_title=canonical_title,
            aliases=aliases,
            members=members,
            distinct_documents=distinct_documents,
            method=method,
            similarity=similarity,
        )
        session.add(decision)
        session.flush()
        return decision

    def list_merge_decisions(
        self, session: Session, *, framework_version_id: str
    ) -> list[KnowledgeMergeDecision]:
        return list(
            session.scalars(
                select(KnowledgeMergeDecision)
                .where(
                    KnowledgeMergeDecision.framework_version_id
                    == framework_version_id
                )
                .order_by(KnowledgeMergeDecision.created_at.asc())
            )
        )

    def list_alias_locks(self, session: Session, *, course_id: str) -> list[tuple[str, str]]:
        return [
            (lock.title_a, lock.title_b)
            for lock in session.scalars(
                select(KnowledgeAliasLock)
                .where(KnowledgeAliasLock.course_id == course_id)
                .order_by(KnowledgeAliasLock.title_a.asc(), KnowledgeAliasLock.title_b.asc())
            )
        ]

    def add_alias_lock(
        self, session: Session, *, course_id: str, title_a: str, title_b: str
    ) -> bool:
        existing = session.scalar(
            select(KnowledgeAliasLock.id)
            .where(KnowledgeAliasLock.course_id == course_id)
            .where(KnowledgeAliasLock.title_a == title_a)
            .where(KnowledgeAliasLock.title_b == title_b)
        )
        if existing is not None:
            return False
        session.add(
            KnowledgeAliasLock(course_id=course_id, title_a=title_a, title_b=title_b)
        )
        session.flush()
        return True

    def delete_alias_lock(
        self, session: Session, *, course_id: str, title_a: str, title_b: str
    ) -> bool:
        lock = session.scalar(
            select(KnowledgeAliasLock)
            .where(KnowledgeAliasLock.course_id == course_id)
            .where(KnowledgeAliasLock.title_a == title_a)
            .where(KnowledgeAliasLock.title_b == title_b)
        )
        if lock is None:
            return False
        session.delete(lock)
        session.flush()
        return True

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
        aliases: list[str] | None = None,
    ) -> KnowledgeNodeVersion:
        node_version = KnowledgeNodeVersion(
            framework_version_id=framework_version_id,
            knowledge_node_id=knowledge_node_id,
            parent_id=parent_id,
            title=title,
            section_label=section_label,
            content=content,
            aliases=aliases,
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
