from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.knowledge import (
    KnowledgeFrameworkVersion,
    KnowledgeNode,
    KnowledgeNodeVersion,
)
from app.llm.base import LLMTemporaryError
from app.llm.openai_compatible import get_llm_adapter
from app.llm.prompts.knowledge_framework import SYSTEM_PROMPT
from app.llm.schemas import (
    KnowledgeFrameworkCandidate,
    KnowledgeNodeCandidate,
    KnowledgeRelationCandidate,
    KnowledgeSourceCandidate,
)
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.job_repository import JobRepository
from app.schemas.knowledge import (
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeFrameworkResponse,
    KnowledgeNodeDetailResponse,
    KnowledgeRelationResponse,
    KnowledgeSourceResponse,
    KnowledgeTreeNodeResponse,
    KnowledgeVersionResponse,
)
PROMPT_VERSION = "knowledge-framework-v4"
FRAMEWORK_BATCH_CHUNK_LIMIT = 12
FRAMEWORK_BATCH_CHAR_LIMIT = 14000
FRAMEWORK_PAGE_PREVIEW_CHARS = 300
FRAMEWORK_OUTLINE_PREVIEW_CHARS = 180
FRAMEWORK_CONTEXT_PAGE_WINDOW = 2
MIN_KNOWLEDGE_CONTENT_CHARS = 24
MAX_KNOWLEDGE_TITLE_CHARS = 120


@dataclass(frozen=True)
class FrameworkSourceUnit:
    document_id: str
    filename: str
    page_number: int
    page_end: int
    text: str
    chunk_id: str | None = None


@dataclass(frozen=True)
class FrameworkBuildBatch:
    index: int
    units: list[FrameworkSourceUnit]


class KnowledgeBuildPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework_version_id: str
    course_id: str
    reference_outline: str | None = None


class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        self.repository = repository or KnowledgeRepository()
        self.job_repository = job_repository or JobRepository()

    def start_build(
        self,
        session: Session,
        *,
        course_id: str,
        request: KnowledgeBuildRequest,
    ) -> KnowledgeBuildResponse:
        adapter = get_llm_adapter()
        adapter.ensure_available()
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )

        documents = self.repository.get_documents_for_framework_build(session, course_id)
        if not documents:
            raise AppError(
                code="MATERIALS_NOT_READY",
                message="At least one parsed material is required before building a knowledge framework.",
                status_code=400,
            )

        version = self.repository.create_framework_version(
            session,
            course_id=course_id,
            version_number=self.repository.next_version_number(session, course_id),
            status="building",
        )
        job = self.job_repository.create_job(
            session,
            job_type="knowledge_framework.build",
            payload_json=KnowledgeBuildPayloadModel(
                course_id=course_id,
                framework_version_id=version.id,
                reference_outline=request.reference_outline,
            ).model_dump(),
            max_attempts=2,
        )
        session.commit()
        return KnowledgeBuildResponse(
            job_id=job.id,
            framework_version_id=version.id,
            status=version.status,
        )

    def build_framework_job(
        self,
        session: Session,
        *,
        course_id: str,
        framework_version_id: str,
        reference_outline: str | None,
    ) -> None:
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )
        version = self.repository.get_framework_version(session, framework_version_id)
        if version is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Knowledge framework version not found.",
                status_code=404,
                details={"framework_version_id": framework_version_id},
            )
        if version.status == "active":
            return

        documents = self.repository.get_documents_for_framework_build(session, course_id)
        if not documents:
            version.status = "failed"
            raise AppError(
                code="MATERIALS_NOT_READY",
                message="Parsed materials are required before building a knowledge framework.",
                status_code=400,
            )

        adapter = get_llm_adapter()
        try:
            with session.begin_nested():
                candidate = self._generate_framework_candidate(
                    adapter=adapter,
                    course_name=course.name,
                    documents=documents,
                    reference_outline=reference_outline,
                )
                ref_to_node_version_id = self._persist_framework_candidate(
                    session,
                    version=version,
                    course_id=course_id,
                    candidate=candidate,
                )
                self._persist_relations(
                    session,
                    version=version,
                    candidate=candidate,
                    ref_to_node_version_id=ref_to_node_version_id,
                )
        except (AppError, LLMTemporaryError):
            version.status = "failed"
            raise
        except Exception as exc:
            version.status = "failed"
            raise AppError(
                code="KNOWLEDGE_BUILD_FAILED",
                message="Knowledge framework build failed unexpectedly.",
                status_code=500,
            ) from exc

        self.repository.deactivate_active_versions(session, course_id)
        version.status = "active"
        version.activated_at = datetime.now(UTC)
        course.active_framework_version_id = version.id

    def list_versions(self, session: Session, course_id: str) -> list[KnowledgeVersionResponse]:
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )
        return [
            KnowledgeVersionResponse(
                id=version.id,
                version_number=version.version_number,
                status=version.status,
                created_at=version.created_at,
                activated_at=version.activated_at,
            )
            for version in self.repository.list_framework_versions(session, course_id)
        ]

    def get_active_framework(self, session: Session, course_id: str) -> KnowledgeFrameworkResponse:
        version = self.repository.get_active_framework(session, course_id)
        if version is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="No active knowledge framework exists for this course.",
                status_code=404,
                details={"course_id": course_id},
            )
        tree = self._build_tree(version.node_versions)
        return KnowledgeFrameworkResponse(
            framework_version_id=version.id,
            version_number=version.version_number,
            status=version.status,
            activated_at=version.activated_at,
            tree=tree,
            nodes=tree,
        )

    def get_node_detail(
        self, session: Session, knowledge_node_id: str
    ) -> KnowledgeNodeDetailResponse:
        node = session.get(KnowledgeNode, knowledge_node_id)
        if node is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Knowledge node not found.",
                status_code=404,
                details={"knowledge_node_id": knowledge_node_id},
            )
        node_version = self.repository.get_active_node_version(
            session,
            course_id=node.course_id,
            knowledge_node_id=knowledge_node_id,
        )
        if node_version is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Knowledge node is not present in the active framework.",
                status_code=404,
                details={"knowledge_node_id": knowledge_node_id},
            )

        relations = [
            KnowledgeRelationResponse(
                target_knowledge_node_id=relation.target_node_version.knowledge_node_id,
                target_title=relation.target_node_version.title,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                evidence=relation.evidence,
            )
            for relation in node_version.outgoing_relations
        ]

        return KnowledgeNodeDetailResponse(
            knowledge_node_id=node_version.knowledge_node_id,
            node_version_id=node_version.id,
            framework_version_id=node_version.framework_version_id,
            section_label=node_version.section_label,
            title=node_version.title,
            content=node_version.content,
            level=node_version.level,
            is_leaf=node_version.is_leaf,
            sources=self._serialize_sources(node_version),
            relations=relations,
        )

    def _persist_framework_candidate(
        self,
        session: Session,
        *,
        version: KnowledgeFrameworkVersion,
        course_id: str,
        candidate: KnowledgeFrameworkCandidate,
    ) -> dict[str, str]:
        ref_to_node_version_id: dict[str, str] = {}
        root_node = self.repository.get_or_create_node(
            session,
            course_id=course_id,
            stable_key=f"root::{candidate.root_title.strip().lower()}",
        )
        root_version = self.repository.add_node_version(
            session,
            framework_version_id=version.id,
            knowledge_node_id=root_node.id,
            parent_id=None,
            title=candidate.root_title,
            section_label=None,
            content=candidate.root_description,
            level=0,
            is_leaf=False,
            sort_order=0,
        )
        ref_to_node_version_id["__root__"] = root_version.id

        for index, child in enumerate(candidate.nodes, start=1):
            self._persist_candidate_node(
                session,
                version=version,
                course_id=course_id,
                node=child,
                parent_id=root_version.id,
                level=1,
                sort_order=index,
                path=[candidate.root_title],
                ref_to_node_version_id=ref_to_node_version_id,
            )
        return ref_to_node_version_id

    def _persist_candidate_node(
        self,
        session: Session,
        *,
        version: KnowledgeFrameworkVersion,
        course_id: str,
        node: KnowledgeNodeCandidate,
        parent_id: str,
        level: int,
        sort_order: int,
        path: list[str],
        ref_to_node_version_id: dict[str, str],
    ) -> None:
        title = node.title.strip()
        if not title:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Knowledge nodes must have non-empty titles.",
                status_code=502,
            )

        section_label = self._clean_section_label(node.section_label)
        stable_key_parts = [*path]
        if section_label:
            stable_key_parts.append(section_label)
        stable_key_parts.append(title)
        stable_key = " > ".join(stable_key_parts).lower()
        knowledge_node = self.repository.get_or_create_node(
            session,
            course_id=course_id,
            stable_key=stable_key,
        )
        node_version = self.repository.add_node_version(
            session,
            framework_version_id=version.id,
            knowledge_node_id=knowledge_node.id,
            parent_id=parent_id,
            title=title,
            section_label=section_label,
            content=node.content,
            level=level,
            is_leaf=not node.children,
            sort_order=sort_order,
        )
        ref_to_node_version_id[node.ref] = node_version.id

        if not node.children and not node.sources:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message=f"Leaf node '{title}' must include at least one grounded source.",
                status_code=502,
            )

        for source in node.sources:
            if not self.repository.document_page_exists(
                session,
                document_id=source.document_id,
                page_number=source.page_number,
            ):
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message=f"Knowledge source for '{title}' points to a missing page.",
                    status_code=502,
                )
            if source.chunk_id and not self.repository.chunk_belongs_to_document(
                session,
                chunk_id=source.chunk_id,
                document_id=source.document_id,
            ):
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message=f"Knowledge source for '{title}' points to a missing chunk.",
                    status_code=502,
                )
            self.repository.add_source(
                session,
                node_version_id=node_version.id,
                document_id=source.document_id,
                page_number=source.page_number,
                chunk_id=source.chunk_id,
                evidence_type=source.evidence_type,
            )

        for index, child in enumerate(node.children, start=1):
            self._persist_candidate_node(
                session,
                version=version,
                course_id=course_id,
                node=child,
                parent_id=node_version.id,
                level=level + 1,
                sort_order=index,
                path=[*path, title],
                ref_to_node_version_id=ref_to_node_version_id,
            )

    def _persist_relations(
        self,
        session: Session,
        *,
        version: KnowledgeFrameworkVersion,
        candidate: KnowledgeFrameworkCandidate,
        ref_to_node_version_id: dict[str, str],
    ) -> None:
        for relation in candidate.relations:
            source_id = ref_to_node_version_id.get(relation.source_ref)
            target_id = ref_to_node_version_id.get(relation.target_ref)
            if source_id is None or target_id is None:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Knowledge relation references an unknown node.",
                    status_code=502,
                )
            self.repository.add_relation(
                session,
                framework_version_id=version.id,
                source_node_version_id=source_id,
                target_node_version_id=target_id,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                evidence=relation.evidence,
            )

    def _generate_framework_candidate(
        self,
        *,
        adapter: Any,
        course_name: str,
        documents: list[Any],
        reference_outline: str | None,
    ) -> KnowledgeFrameworkCandidate:
        batches = self._build_framework_batches(documents)
        if not batches:
            raise AppError(
                code="MATERIALS_NOT_READY",
                message="Parsed materials include no extractable text for framework generation.",
                status_code=400,
            )

        batch_candidates: list[KnowledgeFrameworkCandidate] = []
        for batch in batches:
            payload = self._build_llm_payload(
                course_name,
                documents,
                reference_outline,
                batch=batch,
                batch_count=len(batches),
            )
            try:
                llm_result = adapter.generate_structured_output(
                    prompt_version=PROMPT_VERSION,
                    system_prompt=SYSTEM_PROMPT,
                    user_payload=payload,
                    response_model=KnowledgeFrameworkCandidate,
                )
                candidate = llm_result.data
            except AppError as exc:
                raise exc

            batch_candidates.append(self._sanitize_batch_candidate(candidate, batch))

        return self._merge_batch_candidates(
            course_name=course_name,
            documents=documents,
            candidates=batch_candidates,
            batch_count=len(batches),
        )

    def _build_framework_batches(self, documents: list[Any]) -> list[FrameworkBuildBatch]:
        units: list[FrameworkSourceUnit] = []
        for document in documents:
            for chunk in document.chunks:
                if not chunk.text.strip():
                    continue
                units.append(
                    FrameworkSourceUnit(
                        document_id=document.id,
                        filename=document.filename,
                        page_number=chunk.page_start,
                        page_end=chunk.page_end,
                        text=chunk.text,
                        chunk_id=chunk.id,
                    )
                )
            if document.chunks:
                continue
            for page in document.pages:
                text = page.extracted_text or ""
                if page.extraction_status != "extracted" or not text.strip():
                    continue
                units.append(
                    FrameworkSourceUnit(
                        document_id=document.id,
                        filename=document.filename,
                        page_number=page.page_number,
                        page_end=page.page_number,
                        text=text,
                        chunk_id=None,
                    )
                )

        batches: list[FrameworkBuildBatch] = []
        current_units: list[FrameworkSourceUnit] = []
        current_chars = 0
        for unit in units:
            unit_chars = len(self._normalize_source_text(unit.text))
            exceeds_chars = current_units and current_chars + unit_chars > FRAMEWORK_BATCH_CHAR_LIMIT
            exceeds_units = len(current_units) >= FRAMEWORK_BATCH_CHUNK_LIMIT
            if current_units and (exceeds_chars or exceeds_units):
                batches.append(FrameworkBuildBatch(index=len(batches) + 1, units=current_units))
                current_units = []
                current_chars = 0
            current_units.append(unit)
            current_chars += unit_chars
        if current_units:
            batches.append(FrameworkBuildBatch(index=len(batches) + 1, units=current_units))
        return batches

    def _sanitize_batch_candidate(
        self, candidate: KnowledgeFrameworkCandidate, batch: FrameworkBuildBatch
    ) -> KnowledgeFrameworkCandidate:
        fallback_sources = [
            KnowledgeSourceCandidate(
                document_id=unit.document_id,
                page_number=unit.page_number,
                chunk_id=unit.chunk_id,
                evidence_type="chunk" if unit.chunk_id else "page_excerpt",
            )
            for unit in batch.units
        ]
        valid_pages = {(unit.document_id, unit.page_number) for unit in batch.units}
        valid_chunks = {
            unit.chunk_id
            for unit in batch.units
            if unit.chunk_id is not None
        }

        def sanitize_node(node: KnowledgeNodeCandidate, path: str) -> KnowledgeNodeCandidate | None:
            children: list[KnowledgeNodeCandidate] = []
            for index, child_node in enumerate(node.children, start=1):
                child = sanitize_node(child_node, f"{path}_{index}")
                if child is not None:
                    children.append(child)
            sources = [
                source
                for source in node.sources
                if (source.document_id, source.page_number) in valid_pages
                and (source.chunk_id is None or source.chunk_id in valid_chunks)
            ]
            if not children and not sources and fallback_sources:
                sources = [fallback_sources[0]]
            title = node.title.strip() or "Untitled topic"
            return KnowledgeNodeCandidate(
                ref=f"batch{batch.index}_{path}_{node.ref}",
                section_label=self._clean_section_label(node.section_label),
                title=title[:255],
                content=node.content,
                sources=sources,
                children=children,
            )

        return KnowledgeFrameworkCandidate(
            root_title=candidate.root_title.strip() or "Knowledge Framework",
            root_description=candidate.root_description,
            nodes=[
                node
                for index, child in enumerate(candidate.nodes, start=1)
                if (node := sanitize_node(child, f"node{index}")) is not None
            ],
            relations=[],
        )

    def _merge_batch_candidates(
        self,
        *,
        course_name: str,
        documents: list[Any],
        candidates: list[KnowledgeFrameworkCandidate],
        batch_count: int,
    ) -> KnowledgeFrameworkCandidate:
        """跨批次合并：按来源文档分桶保留「文档 → 知识点」层级。

        此前实现把所有 topic 展平进一个列表（真实模型验收 2026-10-20 D3：
        大材料多批次合并后 98 个叶子全部直接挂根节点）。现在：
        - 去重按文档内标题（跨文档同名保留）；
        - 文档内按最小来源页码排序；
        - section_label 缺失时用标题+内容推断（如 4.2.1），失败留空；
        - relations 只连文档内相邻知识点。
        """
        merged_by_doc: dict[str, list[KnowledgeNodeCandidate]] = {}
        seen_titles_by_doc: dict[str, set[str]] = {}
        topic_counter = 0

        for candidate in candidates:
            for node in candidate.nodes:
                for topic in self._collect_source_backed_topics(node):
                    if not topic.sources:
                        continue
                    document_id = topic.sources[0].document_id
                    if not any(document.id == document_id for document in documents):
                        continue
                    if not self._is_quality_knowledge_topic(topic):
                        continue
                    title_key = self._normalize_title_key(topic.title)
                    seen = seen_titles_by_doc.setdefault(document_id, set())
                    if title_key in seen:
                        continue
                    seen.add(title_key)
                    section_label = self._clean_section_label(topic.section_label)
                    if not section_label:
                        section_label = self._infer_section_label(
                            f"{topic.title or ''} {topic.content or ''}"
                        )
                    topic_counter += 1
                    merged_by_doc.setdefault(document_id, []).append(
                        KnowledgeNodeCandidate(
                            ref=f"topic_{topic_counter}",
                            section_label=section_label,
                            title=topic.title,
                            content=topic.content,
                            sources=topic.sources[:3],
                            children=[],
                        )
                    )

        if not merged_by_doc:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Knowledge framework generation produced no source-backed knowledge points.",
                status_code=502,
            )

        document_by_id = {document.id: document for document in documents}
        doc_nodes: list[KnowledgeNodeCandidate] = []
        relations: list[KnowledgeRelationCandidate] = []
        for document_id, topics in merged_by_doc.items():
            topics.sort(
                key=lambda t: min(
                    (source.page_number for source in t.sources if source.page_number),
                    default=10**9,
                )
            )
            document = document_by_id.get(document_id)
            doc_nodes.append(
                KnowledgeNodeCandidate(
                    ref=f"doc_{document_id}",
                    section_label=None,
                    title=getattr(document, "filename", None) or f"Document {document_id[:8]}",
                    content=None,
                    sources=[],
                    children=topics,
                )
            )
            relations.extend(
                KnowledgeRelationCandidate(
                    source_ref=left.ref,
                    target_ref=right.ref,
                    relation_type="related",
                    confidence=0.4,
                    evidence="Adjacent knowledge points from the same source document.",
                )
                for left, right in zip(topics, topics[1:])
            )

        return KnowledgeFrameworkCandidate(
            root_title=course_name,
            root_description=f"Generated from {len(documents)} parsed material(s) across {batch_count} batch(es).",
            nodes=doc_nodes,
            relations=relations,
        )

    def _collect_source_backed_topics(
        self, node: KnowledgeNodeCandidate
    ) -> list[KnowledgeNodeCandidate]:
        topics: list[KnowledgeNodeCandidate] = []
        if node.sources:
            topics.append(
                KnowledgeNodeCandidate(
                    ref=node.ref,
                    section_label=node.section_label,
                    title=node.title,
                    content=node.content,
                    sources=node.sources,
                    children=[],
                )
            )
        for child in node.children:
            topics.extend(self._collect_source_backed_topics(child))
        return topics

    def _normalize_title_key(self, title: str) -> str:
        return " ".join(title.lower().split())

    def _clean_section_label(self, section_label: str | None) -> str | None:
        if not section_label:
            return None
        normalized = " ".join(section_label.split()).strip(" .:-")
        if not normalized:
            return None
        return normalized[:100]

    def _infer_section_label(self, text: str) -> str | None:
        normalized = " ".join(text.split())
        match = re.search(r"\b(?:chapter\s+)?(\d+(?:\.\d+){0,3})\b", normalized, flags=re.IGNORECASE)
        if match:
            # 排除标准号/年份（如 802.3、2014）：章节号首位数字不会太大
            if int(match.group(1).split(".")[0]) > 50:
                return None
            if "chapter" in match.group(0).lower():
                return match.group(0).title()
            return match.group(1)
        chapter_match = re.search(r"\bchapter\s+\d+\b", normalized, flags=re.IGNORECASE)
        if chapter_match:
            return chapter_match.group(0).title()
        return None

    def _is_quality_knowledge_topic(self, topic: KnowledgeNodeCandidate) -> bool:
        title = " ".join(topic.title.split())
        content = " ".join((topic.content or "").split())
        title_lower = title.lower()
        combined_lower = f"{title_lower} {content.lower()}"
        rejected_markers = {
            "table of contents",
            "contents",
            "agenda",
            "acknowledgement",
            "acknowledgment",
            "copyright",
            "course outline",
            "chapter outline",
        }
        if not title or len(title) > MAX_KNOWLEDGE_TITLE_CHARS:
            return False
        if any(marker in combined_lower for marker in rejected_markers):
            return False
        if not content or len(content) < MIN_KNOWLEDGE_CONTENT_CHARS:
            return False
        return True

    def _build_llm_payload(
        self,
        course_name: str,
        documents: list[Any],
        reference_outline: str | None,
        *,
        batch: FrameworkBuildBatch,
        batch_count: int,
    ) -> dict[str, Any]:
        units_by_document: dict[str, list[FrameworkSourceUnit]] = {}
        for unit in batch.units:
            units_by_document.setdefault(unit.document_id, []).append(unit)

        document_payloads = []
        for document in documents:
            document_units = units_by_document.get(document.id, [])
            if not document_units:
                continue
            content, source_segments = self._join_source_units(document_units)
            document_payloads.append(
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "content": content,
                    "source_segments": source_segments,
                    "nearby_page_context": self._build_nearby_page_context(
                        document, document_units
                    ),
                    "pages": [
                        {
                            "page_number": page.page_number,
                            "extraction_status": page.extraction_status,
                            "text_preview": (page.extracted_text or "")[:FRAMEWORK_PAGE_PREVIEW_CHARS],
                        }
                        for page in document.pages
                        if any(unit.page_number == page.page_number for unit in document_units)
                    ],
                    "batch_sources": [
                        {
                            "document_id": unit.document_id,
                            "page_number": unit.page_number,
                            "chunk_id": unit.chunk_id,
                        }
                        for unit in document_units
                    ],
                }
            )

        return {
            "course_name": course_name,
            "reference_outline": reference_outline,
            "task": (
                "Extract concise source-backed knowledge points from the current batch. "
                "Return only teachable concepts with a title, explanation, optional section "
                "label, and grounded sources."
            ),
            "generation_scope": {
                "batch_index": batch.index,
                "batch_count": batch_count,
                "instruction": (
                    "Generate source-backed knowledge points only for this batch. Use "
                    "the continuous document content as the primary evidence. Use "
                    "nearby_page_context only to understand section labels and neighboring "
                    "meaning. Cite only supplied document_id, page_number, and chunk_id values "
                    "from batch_sources or source_segments."
                ),
            },
            "selection_rules": [
                "Keep concepts, mechanisms, principles, design questions, tradeoffs, metrics, misconceptions, and skills.",
                "Discard cover slides, table-of-contents text, agenda bullets, repeated headers or footers, course/chapter labels, and page numbers.",
                "Discard isolated code snippets, formulas, acronyms, decorative labels, and raw bullet fragments unless the surrounding context makes them a teachable idea.",
                "Merge adjacent or repeated fragments that describe the same idea into one leaf node with multiple sources.",
                "Prefer concise academic titles such as 'Temporal locality' or 'Cache design tradeoffs', not copied slide text.",
                "Keep titles to a short noun phrase; never use a full sentence or the first sentence of the source as a title.",
                "Use the continuous document content as the primary evidence; source_segments are provenance metadata, not concepts.",
                "Put chapter or section markers in section_label, not in title.",
                "Do not create document, chapter, or section container nodes.",
                "Each leaf node must include at least one source from batch_sources.",
            ],
            "output_shape": {
                "root_title": "Course or unit title.",
                "nodes": (
                    "A flat list of high-signal knowledge point nodes. children should usually "
                    "be empty. Do not include document or section containers."
                ),
                "node_fields": {
                    "section_label": "Optional chapter or section marker, for example '3.1'.",
                    "title": "Short concept name.",
                    "content": "Complete, source-grounded teaching explanation of the concept.",
                },
                "relations": "Optional relations between returned node refs.",
            },
            "documents": document_payloads,
        }

    def _normalize_source_text(self, text: str) -> str:
        lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").split("\n")]
        normalized_lines: list[str] = []
        previous_blank = False
        for line in lines:
            if not line:
                if not previous_blank and normalized_lines:
                    normalized_lines.append("")
                previous_blank = True
                continue
            normalized_lines.append(line)
            previous_blank = False
        return "\n".join(normalized_lines).strip()

    def _join_source_units(
        self, units: list[FrameworkSourceUnit]
    ) -> tuple[str, list[dict[str, Any]]]:
        content_parts: list[str] = []
        source_segments: list[dict[str, Any]] = []
        offset = 0
        for unit in units:
            text = self._normalize_source_text(unit.text)
            if not text:
                continue
            if content_parts:
                content_parts.append("\n\n")
                offset += 2
            start = offset
            content_parts.append(text)
            offset += len(text)
            source_segments.append(
                {
                    "chunk_id": unit.chunk_id,
                    "page_start": unit.page_number,
                    "page_end": unit.page_end,
                    "start_char": start,
                    "end_char": offset,
                }
            )
        return "".join(content_parts), source_segments

    def _build_nearby_page_context(
        self, document: Any, units: list[FrameworkSourceUnit]
    ) -> list[dict[str, Any]]:
        context: list[dict[str, Any]] = []
        if not units:
            return context
        batch_pages = {unit.page_number for unit in units}
        min_page = min(batch_pages) - FRAMEWORK_CONTEXT_PAGE_WINDOW
        max_page = max(batch_pages) + FRAMEWORK_CONTEXT_PAGE_WINDOW
        for page in document.pages:
            if page.extraction_status != "extracted":
                continue
            if page.page_number < min_page or page.page_number > max_page:
                continue
            text = " ".join((page.extracted_text or "").split())
            if not text:
                continue
            context.append(
                {
                    "page_number": page.page_number,
                    "in_current_batch": page.page_number in batch_pages,
                    "text_preview": text[:FRAMEWORK_OUTLINE_PREVIEW_CHARS],
                }
            )
        return context

    def _build_tree(
        self, node_versions: list[KnowledgeNodeVersion]
    ) -> list[KnowledgeTreeNodeResponse]:
        node_lookup = {node.id: node for node in node_versions}
        children_map: dict[str | None, list[KnowledgeNodeVersion]] = {}
        for node in node_versions:
            children_map.setdefault(node.parent_id, []).append(node)

        def convert(node: KnowledgeNodeVersion) -> KnowledgeTreeNodeResponse:
            return KnowledgeTreeNodeResponse(
                knowledge_node_id=node.knowledge_node_id,
                node_version_id=node.id,
                section_label=node.section_label,
                title=node.title,
                content=node.content,
                level=node.level,
                is_leaf=node.is_leaf,
                sources=self._serialize_sources(node),
                children=[
                    convert(child)
                    for child in sorted(
                        children_map.get(node.id, []), key=lambda item: item.sort_order
                    )
                ],
            )

        roots = sorted(children_map.get(None, []), key=lambda item: item.sort_order)
        if not roots:
            return []
        root = roots[0]
        return [convert(child) for child in sorted(children_map.get(root.id, []), key=lambda item: item.sort_order)]

    def _serialize_sources(
        self, node: KnowledgeNodeVersion
    ) -> list[KnowledgeSourceResponse]:
        return [
            KnowledgeSourceResponse(
                document_id=source.document_id,
                filename=source.document.filename,
                page_number=source.page_number,
                chunk_id=source.chunk_id,
                evidence_type=source.evidence_type,
            )
            for source in node.sources
        ]
