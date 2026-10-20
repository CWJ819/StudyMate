from __future__ import annotations

import re
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
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
from app.repositories.llm_repository import LLMRepository
from app.schemas.knowledge import (
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeFrameworkResponse,
    KnowledgeIdentityDiagnosticsResponse,
    KnowledgeIdentityMatchResponse,
    KnowledgeNodeDetailResponse,
    KnowledgeRelationResponse,
    KnowledgeSourceResponse,
    KnowledgeTreeNodeResponse,
    KnowledgeVersionResponse,
)
PROMPT_VERSION = "knowledge-framework-v4"
FRAMEWORK_BATCH_CHUNK_LIMIT = 12
FRAMEWORK_BATCH_CHAR_LIMIT = 14000
FRAMEWORK_LLM_CONCURRENCY = 3
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
        llm_repository: LLMRepository | None = None,
    ) -> None:
        self.repository = repository or KnowledgeRepository()
        self.job_repository = job_repository or JobRepository()
        self.llm_repository = llm_repository or LLMRepository()

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

        building_version = self.repository.get_building_framework(session, course_id)
        if building_version is not None:
            raise AppError(
                code="KNOWLEDGE_BUILD_IN_PROGRESS",
                message="A knowledge framework build is already running for this course.",
                status_code=409,
                details={"framework_version_id": building_version.id},
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
            input_revision=course.material_revision,
            input_document_ids=[document.id for document in documents],
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

        if version.input_revision != course.material_revision:
            version.status = "failed"
            raise AppError(
                code="KNOWLEDGE_INPUT_STALE",
                message="The source materials changed while this framework was waiting to build. Start a new build.",
                status_code=409,
                details={"framework_version_id": framework_version_id},
            )

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
            candidate = self._generate_framework_candidate(
                session=session,
                framework_version_id=version.id,
                course_id=course_id,
                adapter=adapter,
                course_name=course.name,
                documents=documents,
                reference_outline=reference_outline,
            )
            with session.begin_nested():
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
                input_revision=version.input_revision,
            )
            for version in self.repository.list_framework_versions(session, course_id)
        ]

    def identity_diagnostics(
        self, session: Session, course_id: str
    ) -> KnowledgeIdentityDiagnosticsResponse:
        if self.repository.get_course(session, course_id) is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND", message="Course not found.", status_code=404,
                details={"course_id": course_id},
            )
        current, previous = self.repository.get_latest_framework_pair(session, course_id)
        if current is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND", message="No active knowledge framework exists for this course.",
                status_code=404, details={"course_id": course_id},
            )
        if previous is None:
            return KnowledgeIdentityDiagnosticsResponse(
                current_version_id=current.id, previous_version_id=None, matches=[]
            )
        previous_by_node = {node.knowledge_node_id: node for node in previous.node_versions if node.is_leaf}
        previous_leaves = [node for node in previous.node_versions if node.is_leaf]
        matches: list[KnowledgeIdentityMatchResponse] = []
        for node in (candidate for candidate in current.node_versions if candidate.is_leaf):
            exact = previous_by_node.get(node.knowledge_node_id)
            if exact is not None:
                matches.append(self._identity_match(node, exact, 1.0, "stable_identity", True))
                continue
            scored = sorted(
                ((self._identity_score(node, old), old) for old in previous_leaves),
                key=lambda item: item[0], reverse=True,
            )
            best = scored[0] if scored else (0.0, None)
            second = scored[1][0] if len(scored) > 1 else 0.0
            confidence, old = best
            if old is not None and confidence >= 0.85 and confidence - second >= 0.1:
                matches.append(self._identity_match(node, old, confidence, "high_confidence_content_match", True))
            elif old is not None and confidence >= 0.6:
                matches.append(self._identity_match(node, old, confidence, "review_required", False))
            else:
                matches.append(self._identity_match(node, None, confidence, "unmatched", False))
        return KnowledgeIdentityDiagnosticsResponse(
            current_version_id=current.id,
            previous_version_id=previous.id,
            matches=matches,
        )

    def _identity_match(
        self, current: KnowledgeNodeVersion, previous: KnowledgeNodeVersion | None,
        confidence: float, match_type: str, safe_to_migrate: bool,
    ) -> KnowledgeIdentityMatchResponse:
        return KnowledgeIdentityMatchResponse(
            current_node_id=current.knowledge_node_id,
            current_title=current.title,
            previous_node_id=previous.knowledge_node_id if previous else None,
            previous_title=previous.title if previous else None,
            confidence=round(confidence, 6), match_type=match_type,
            safe_to_migrate=safe_to_migrate,
        )

    def _identity_score(self, current: KnowledgeNodeVersion, previous: KnowledgeNodeVersion) -> float:
        title_a = self._identity_tokens(current.title)
        title_b = self._identity_tokens(previous.title)
        title_score = len(title_a & title_b) / max(1, len(title_a | title_b))
        content_a = self._identity_tokens(current.content or "")
        content_b = self._identity_tokens(previous.content or "")
        content_score = len(content_a & content_b) / max(1, len(content_a | content_b))
        return title_score * 0.75 + content_score * 0.25

    def _identity_tokens(self, value: str) -> set[str]:
        return {token for token in re.findall(r"[\w\u4e00-\u9fff]+", value.lower()) if len(token) > 1}

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
        session: Session,
        framework_version_id: str,
        course_id: str,
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

        checkpoint_rows = self.repository.get_build_batches(session, framework_version_id)
        checkpoints = {row.batch_index: row for row in checkpoint_rows}
        for batch in batches:
            input_hash = self._batch_input_hash(batch)
            checkpoint = checkpoints.get(batch.index)
            if checkpoint is None:
                checkpoint = self.repository.create_build_batch(
                    session,
                    framework_version_id=framework_version_id,
                    batch_index=batch.index,
                    input_hash=input_hash,
                )
                checkpoints[batch.index] = checkpoint
            elif checkpoint.input_hash != input_hash:
                checkpoint.input_hash = input_hash
                checkpoint.status = "pending"
                checkpoint.candidate_json = None
                checkpoint.error_code = None

            if checkpoint.status != "succeeded":
                reusable = self.repository.get_reusable_batch_candidate(
                    session,
                    course_id=course_id,
                    framework_version_id=framework_version_id,
                    batch_index=batch.index,
                    input_hash=input_hash,
                )
                if reusable is not None:
                    checkpoint.status = "succeeded"
                    checkpoint.candidate_json = reusable
                    checkpoint.error_code = None

        session.flush()

        def generate_batch(batch: FrameworkBuildBatch) -> tuple[KnowledgeFrameworkCandidate, Any]:
            payload = self._build_llm_payload(
                course_name,
                documents,
                reference_outline,
                batch=batch,
                batch_count=len(batches),
            )
            llm_result = adapter.generate_structured_output(
                prompt_version=PROMPT_VERSION,
                system_prompt=SYSTEM_PROMPT,
                user_payload=payload,
                response_model=KnowledgeFrameworkCandidate,
            )
            return self._sanitize_batch_candidate(llm_result.data, batch), llm_result.summary

        pending_batches = [
            batch
            for batch in batches
            if checkpoints[batch.index].status != "succeeded"
            or not checkpoints[batch.index].candidate_json
        ]
        with ThreadPoolExecutor(max_workers=min(FRAMEWORK_LLM_CONCURRENCY, len(pending_batches) or 1)) as executor:
            futures = {executor.submit(generate_batch, batch): batch for batch in pending_batches}
            for future, batch in [(future, futures[future]) for future in futures]:
                try:
                    candidate, summary = future.result()
                except Exception as exc:
                    checkpoints[batch.index].status = "failed"
                    checkpoints[batch.index].error_code = getattr(exc, "code", type(exc).__name__)
                    adapter_settings = getattr(adapter, "settings", None)
                    self.llm_repository.add_call_log(
                        session,
                        course_id=course_id,
                        operation="knowledge_framework.batch",
                        provider="mock" if getattr(adapter_settings, "llm_base_url", "").startswith("mock://") else "openai-compatible",
                        model_name=getattr(adapter_settings, "llm_model", None) or "unknown",
                        prompt_version=PROMPT_VERSION,
                        status="failed",
                        error_code=getattr(exc, "code", type(exc).__name__),
                        input_summary={"batch_index": batch.index, "batch_count": len(batches), "unit_count": len(batch.units)},
                    )
                    session.commit()
                    raise
                checkpoints[batch.index].status = "succeeded"
                checkpoints[batch.index].candidate_json = candidate.model_dump()
                checkpoints[batch.index].error_code = None
                self.llm_repository.add_call_log(
                    session,
                    course_id=course_id,
                    operation="knowledge_framework.batch",
                    provider=summary.provider,
                    model_name=summary.model_name,
                    prompt_version=summary.prompt_version,
                    status="succeeded",
                    attempt_count=summary.attempt_count,
                    duration_ms=summary.duration_ms,
                    input_summary={"batch_index": batch.index, "batch_count": len(batches), "unit_count": len(batch.units)},
                    output_summary={"candidate_node_count": len(candidate.nodes)},
                )
                session.commit()

        batch_candidates = [
            KnowledgeFrameworkCandidate.model_validate(checkpoints[batch.index].candidate_json)
            for batch in batches
        ]

        return self._merge_batch_candidates(
            course_name=course_name,
            documents=documents,
            candidates=batch_candidates,
            batch_count=len(batches),
        )

    def _batch_input_hash(self, batch: FrameworkBuildBatch) -> str:
        payload = [
            {
                "document_id": unit.document_id,
                "page_number": unit.page_number,
                "page_end": unit.page_end,
                "chunk_id": unit.chunk_id,
                "text": self._normalize_source_text(unit.text),
            }
            for unit in batch.units
        ]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

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
        merged_topics: list[KnowledgeNodeCandidate] = []
        grouped_topics: dict[str | None, list[KnowledgeNodeCandidate]] = {}
        seen_titles: set[tuple[str | None, str]] = set()

        for candidate in candidates:
            for node in candidate.nodes:
                for topic in self._collect_source_backed_topics(node):
                    if not topic.sources:
                        continue
                    document_id = topic.sources[0].document_id
                    if not any(document.id == document_id for document in documents):
                        continue
                    section_key = self._clean_section_label(topic.section_label)
                    title_key = self._normalize_title_key(topic.title)
                    dedupe_key = (section_key, title_key)
                    if dedupe_key in seen_titles:
                        continue
                    if not self._is_quality_knowledge_topic(topic):
                        continue
                    seen_titles.add(dedupe_key)
                    topic_index = len(merged_topics) + 1
                    normalized_topic = KnowledgeNodeCandidate(
                            ref=f"topic_{topic_index}",
                            section_label=section_key,
                            title=topic.title,
                            content=topic.content,
                            sources=topic.sources[:3],
                            children=[],
                        )
                    merged_topics.append(normalized_topic)
                    grouped_topics.setdefault(section_key, []).append(normalized_topic)

        if not merged_topics:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Knowledge framework generation produced no source-backed knowledge points.",
                status_code=502,
            )

        relations = [
            KnowledgeRelationCandidate(
                source_ref=left.ref,
                target_ref=right.ref,
                relation_type="related",
                confidence=0.4,
                evidence="Adjacent knowledge points from the same source material batch.",
            )
            for left, right in zip(merged_topics, merged_topics[1:])
        ]

        merged_nodes: list[KnowledgeNodeCandidate] = []
        for section_key, topics in grouped_topics.items():
            if section_key is None:
                merged_nodes.extend(topics)
                continue
            merged_nodes.append(
                KnowledgeNodeCandidate(
                    ref=f"section_{len(merged_nodes) + 1}",
                    section_label=section_key,
                    title=section_key,
                    content=None,
                    sources=[],
                    children=topics,
                )
            )

        result = KnowledgeFrameworkCandidate(
            root_title=course_name,
            root_description=f"Generated from {len(documents)} parsed material(s) across {batch_count} batch(es).",
            nodes=merged_nodes,
            relations=relations,
        )
        self._validate_framework_structure(result)
        return result

    def _collect_source_backed_topics(
        self,
        node: KnowledgeNodeCandidate,
        inherited_section_label: str | None = None,
    ) -> list[KnowledgeNodeCandidate]:
        topics: list[KnowledgeNodeCandidate] = []
        section_label = self._clean_section_label(node.section_label) or inherited_section_label
        if node.children:
            for child in node.children:
                topics.extend(self._collect_source_backed_topics(child, section_label))
            return topics
        if node.sources:
            topics.append(
                KnowledgeNodeCandidate(
                    ref=node.ref,
                    section_label=section_label,
                    title=node.title,
                    content=node.content,
                    sources=node.sources,
                    children=[],
                )
            )
        return topics

    def _validate_framework_structure(self, candidate: KnowledgeFrameworkCandidate) -> None:
        max_depth = 0
        leaf_count = 0
        seen_refs: set[str] = set()

        def visit(node: KnowledgeNodeCandidate, depth: int) -> None:
            nonlocal max_depth, leaf_count
            if node.ref in seen_refs:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Knowledge framework contains duplicate node references.",
                    status_code=502,
                )
            seen_refs.add(node.ref)
            max_depth = max(max_depth, depth)
            if depth > 4:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Knowledge framework nesting is deeper than the supported limit.",
                    status_code=502,
                )
            if node.children:
                if node.sources:
                    raise AppError(
                        code="LLM_OUTPUT_INVALID",
                        message=f"Container node '{node.title}' must not carry leaf sources.",
                        status_code=502,
                    )
                for child in node.children:
                    visit(child, depth + 1)
                return
            leaf_count += 1
            if not node.sources:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message=f"Leaf node '{node.title}' must include a grounded source.",
                    status_code=502,
                )

        for node in candidate.nodes:
            visit(node, 1)
        if leaf_count == 0:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Knowledge framework must contain at least one leaf node.",
                status_code=502,
            )

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
                "Create a chapter or section container only when the source provides a clear section label; otherwise keep the concept at the nearest reliable level.",
                "Each leaf node must include at least one source from batch_sources.",
            ],
            "output_shape": {
                "root_title": "Course or unit title.",
                "nodes": (
                "A hierarchy of optional section containers and source-backed leaf concepts. "
                "Use children for reliable chapter/section structure; do not use filenames as containers."
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
