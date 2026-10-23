from __future__ import annotations

from datetime import UTC, datetime

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
from app.repositories.knowledge_repository import KnowledgeRepository
from app.repositories.job_repository import JobRepository
from app.repositories.mastery_repository import MasteryRepository
from app.schemas.knowledge import (
    KnowledgeAliasLockResponse,
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeFrameworkResponse,
    KnowledgeMergeDecisionResponse,
    KnowledgeMergeDecisionsResponse,
    KnowledgeGraphEdgeResponse,
    KnowledgeGraphNodeResponse,
    KnowledgeGraphResponse,
    KnowledgeHighlightItemResponse,
    KnowledgeHighlightsResponse,
    KnowledgeNodeDetailResponse,
    KnowledgeRelationResponse,
    KnowledgeScoreReasonResponse,
    KnowledgeScoredTreeNodeResponse,
    KnowledgeScoredTreeResponse,
    KnowledgeScoringBasisResponse,
    KnowledgeScoringWeightsResponse,
    KnowledgeSourceResponse,
    KnowledgeTreeNodeResponse,
    KnowledgeVersionResponse,
)
from app.services.knowledge_pipeline import KnowledgeBuildPipeline
from app.services.knowledge_scoring import (
    DIFFICULTY_WEIGHTS,
    HIGHLIGHT_LIMIT_DEFAULT,
    HIGHLIGHT_ORDERS,
    IMPORTANCE_WEIGHTS,
    SCORING_VERSION,
    HighlightCandidate,
    LeafScore,
    LeafScoringInput,
    RelationEdge,
    rank_highlights,
    score_leaves,
)

# v5 起构建走三阶段流水线（outline → per-section extract → merge/activate）。
# D5 修复：job 不再自动重跑，失败由用户重新触发并复用 section 缓存续跑。
BUILD_JOB_MAX_ATTEMPTS = 1


def _normalize_alias_pair(title_a: str, title_b: str) -> tuple[str, str]:
    first = " ".join(title_a.split())
    second = " ".join(title_b.split())
    if not first or not second:
        raise AppError(
            code="VALIDATION_ERROR",
            message="Alias lock titles must not be empty.",
            status_code=422,
        )
    if first.casefold() == second.casefold():
        raise AppError(
            code="VALIDATION_ERROR",
            message="Alias lock requires two distinct titles.",
            status_code=422,
            details={"title": first},
        )
    if first.casefold() <= second.casefold():
        return first, second
    return second, first


class KnowledgeBuildPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework_version_id: str
    course_id: str
    reference_outline: str | None = None
    job_id: str | None = None


class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository | None = None,
        job_repository: JobRepository | None = None,
        mastery_repository: MasteryRepository | None = None,
    ) -> None:
        self.repository = repository or KnowledgeRepository()
        self.job_repository = job_repository or JobRepository()
        self.mastery_repository = mastery_repository or MasteryRepository()

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

        building = self.repository.get_building_framework_version(session, course_id)
        if building is not None:
            # 自愈：building 版本对应的 job 已终态（进程崩溃遗留）→ 标记失败后放行
            if self.repository.has_pending_build_job(
                session, framework_version_id=building.id
            ):
                raise AppError(
                    code="KNOWLEDGE_BUILD_IN_PROGRESS",
                    message="A knowledge framework build is already in progress for this course.",
                    status_code=409,
                    details={
                        "framework_version_id": building.id,
                        "course_id": course_id,
                    },
                )
            building.status = "failed"

        version = self.repository.create_framework_version(
            session,
            course_id=course_id,
            version_number=self.repository.next_version_number(session, course_id),
            status="building",
        )
        job = self.job_repository.create_job(
            session,
            job_type="knowledge_framework.build",
            payload_json={},
            max_attempts=BUILD_JOB_MAX_ATTEMPTS,
        )
        job.payload_json = KnowledgeBuildPayloadModel(
            course_id=course_id,
            framework_version_id=version.id,
            reference_outline=request.reference_outline,
            job_id=job.id,
        ).model_dump()
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
        job_id: str | None = None,
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
            KnowledgeBuildPipeline(self.repository).run(
                session,
                adapter=adapter,
                course=course,
                version=version,
                documents=documents,
                reference_outline=reference_outline,
                job_id=job_id,
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
            aliases=list(node_version.aliases or []),
            level=node_version.level,
            is_leaf=node_version.is_leaf,
            sources=self._serialize_sources(node_version),
            relations=relations,
        )

    def get_relation_graph(
        self, session: Session, course_id: str
    ) -> KnowledgeGraphResponse:
        """active 版本的关系图：只返回有关系的节点与其间的边。

        关系是版本作用域的，所以这里不跨版本合并；节点 section_path 用于前端
        把边放回章节语境里。
        """
        version = self._require_active_framework(session, course_id)
        versions_by_id = {node.id: node for node in version.node_versions}
        section_paths = self._section_paths(version.node_versions)

        # 读取层双保险：历史版本可能因旧 bug 在同一框架里落下同一 node 的多行
        # version。按 knowledge_node_id 聚合，边按 (source,target,type) 去重并保留
        # 置信度最高的一条，保证 API 输出“一节点一行、一逻辑边一行”。
        edges_by_key: dict[tuple[str, str, str], KnowledgeGraphEdgeResponse] = {}
        connected: set[str] = set()
        for relation in version.relations:
            source = versions_by_id.get(relation.source_node_version_id)
            target = versions_by_id.get(relation.target_node_version_id)
            if source is None or target is None:
                continue
            key = (
                source.knowledge_node_id,
                target.knowledge_node_id,
                relation.relation_type,
            )
            existing = edges_by_key.get(key)
            if existing is not None and existing.confidence >= relation.confidence:
                continue
            edges_by_key[key] = KnowledgeGraphEdgeResponse(
                source=source.knowledge_node_id,
                target=target.knowledge_node_id,
                relation_type=relation.relation_type,
                confidence=relation.confidence,
                evidence=relation.evidence,
            )
            connected.add(source.knowledge_node_id)
            connected.add(target.knowledge_node_id)
        edges = sorted(
            edges_by_key.values(),
            key=lambda edge: (
                edge.source,
                edge.target,
                edge.relation_type,
                -edge.confidence,
            ),
        )

        children_map: dict[str | None, list[KnowledgeNodeVersion]] = {}
        for node in version.node_versions:
            children_map.setdefault(node.parent_id, []).append(node)
        nodes: list[KnowledgeGraphNodeResponse] = []
        seen_nodes: set[str] = set()
        stack = [
            node
            for node in sorted(
                children_map.get(None, []), key=lambda item: item.sort_order
            )
        ]
        while stack:
            node = stack.pop()
            if (
                node.level > 0
                and node.knowledge_node_id in connected
                and node.knowledge_node_id not in seen_nodes
            ):
                seen_nodes.add(node.knowledge_node_id)
                nodes.append(
                    KnowledgeGraphNodeResponse(
                        knowledge_node_id=node.knowledge_node_id,
                        title=node.title,
                        section_path=section_paths.get(node.id, []),
                        is_leaf=node.is_leaf,
                    )
                )
            stack.extend(
                sorted(
                    children_map.get(node.id, []),
                    key=lambda item: item.sort_order,
                    reverse=True,
                )
            )

        return KnowledgeGraphResponse(
            framework_version_id=version.id,
            nodes=nodes,
            edges=edges,
        )

    # ------------------------------------------------------------------
    # Phase 3：importance / difficulty（读取时计算，不落库）
    # ------------------------------------------------------------------

    @staticmethod
    def _dedupe_leaf_versions(
        node_versions: list[KnowledgeNodeVersion],
    ) -> list[KnowledgeNodeVersion]:
        """旧数据可能在同一版本里给同一 node 落多行叶 version。

        读取层按 knowledge_node_id 保留首见行；容器不参与去重（它们不承载
        关系与评分分量）。
        """
        seen_leaf_ids: set[str] = set()
        deduped: list[KnowledgeNodeVersion] = []
        for node in node_versions:
            if node.is_leaf:
                if node.knowledge_node_id in seen_leaf_ids:
                    continue
                seen_leaf_ids.add(node.knowledge_node_id)
            deduped.append(node)
        return deduped

    def get_scored_tree(
        self, session: Session, course_id: str
    ) -> KnowledgeScoredTreeResponse:
        """带评分的章节树：叶子带自身分数与五分量，容器取后代最大值。"""
        version = self._require_active_framework(session, course_id)
        scores = self._score_framework(session, version)

        children_map: dict[str | None, list[KnowledgeNodeVersion]] = {}
        for node in self._dedupe_leaf_versions(version.node_versions):
            children_map.setdefault(node.parent_id, []).append(node)

        def convert(node: KnowledgeNodeVersion) -> KnowledgeScoredTreeNodeResponse:
            children: list[KnowledgeScoredTreeNodeResponse] = []
            for child in sorted(
                children_map.get(node.id, []), key=lambda item: item.sort_order
            ):
                children.append(convert(child))
            score = scores.get(node.id)
            if node.is_leaf:
                importance = score.importance if score is not None else 0.0
                difficulty = score.difficulty if score is not None else 0.0
                components = dict(score.components) if score is not None else None
            else:
                importance = max(
                    (child.importance for child in children), default=0.0
                )
                difficulty = max(
                    (child.difficulty for child in children), default=0.0
                )
                components = None
            return KnowledgeScoredTreeNodeResponse(
                knowledge_node_id=node.knowledge_node_id,
                node_version_id=node.id,
                section_label=node.section_label,
                title=node.title,
                content=node.content,
                level=node.level,
                is_leaf=node.is_leaf,
                sources=self._serialize_sources(node),
                importance=round(importance, 4),
                difficulty=round(difficulty, 4),
                components=components,
                children=children,
            )

        roots = sorted(children_map.get(None, []), key=lambda item: item.sort_order)
        tree: list[KnowledgeScoredTreeNodeResponse] = []
        if roots:
            root = roots[0]
            tree = [
                convert(child)
                for child in sorted(
                    children_map.get(root.id, []), key=lambda item: item.sort_order
                )
            ]
        return KnowledgeScoredTreeResponse(
            framework_version_id=version.id,
            version_number=version.version_number,
            scoring_version=SCORING_VERSION,
            tree=tree,
        )

    def get_highlights(
        self,
        session: Session,
        course_id: str,
        *,
        limit: int = HIGHLIGHT_LIMIT_DEFAULT,
        order: str = "importance",
    ) -> KnowledgeHighlightsResponse:
        """重难点排行：importance / difficulty / gap（importance × (1 − mastery)）。

        掌握度用 active 版本叶子上的现有状态；未测验的叶子 mastery_estimate=None，
        在 gap 排序里排到最后并带 untested 标记（未测验 ≠ 薄弱）。
        """
        if order not in HIGHLIGHT_ORDERS:
            raise AppError(
                code="VALIDATION_ERROR",
                message="Unsupported highlight order.",
                status_code=422,
                details={"order": order, "allowed": list(HIGHLIGHT_ORDERS)},
            )
        version = self._require_active_framework(session, course_id)
        scores = self._score_framework(session, version)
        section_paths = self._section_paths(version.node_versions)
        states = {
            state.knowledge_node_id: state
            for state in self.mastery_repository.list_states(session, course_id)
        }

        candidates: list[HighlightCandidate] = []
        seen_leaf_ids: set[str] = set()
        for node in version.node_versions:
            if not node.is_leaf or node.knowledge_node_id in seen_leaf_ids:
                continue
            seen_leaf_ids.add(node.knowledge_node_id)
            score = scores.get(node.id)
            if score is None:
                continue
            state = states.get(node.knowledge_node_id)
            candidates.append(
                HighlightCandidate(
                    knowledge_node_id=node.knowledge_node_id,
                    title=node.title,
                    section_path=section_paths.get(node.id, []),
                    importance=score.importance,
                    difficulty=score.difficulty,
                    mastery_estimate=(
                        float(state.mastery_estimate) if state is not None else None
                    ),
                    evidence_count=int(state.evidence_count) if state is not None else 0,
                    reasons=list(score.reasons),
                )
            )

        ranked = rank_highlights(candidates, order=order, limit=limit)
        return KnowledgeHighlightsResponse(
            items=[
                KnowledgeHighlightItemResponse(
                    knowledge_node_id=item.knowledge_node_id,
                    title=item.title,
                    section_path=list(item.section_path),
                    importance=item.importance,
                    difficulty=item.difficulty,
                    mastery_estimate=item.mastery_estimate,
                    evidence_count=item.evidence_count,
                    untested=item.mastery_estimate is None,
                    reasons=[
                        KnowledgeScoreReasonResponse(**reason) for reason in item.reasons
                    ],
                )
                for item in ranked
            ],
            basis=KnowledgeScoringBasisResponse(
                scoring_version=SCORING_VERSION,
                weights=KnowledgeScoringWeightsResponse(
                    importance=dict(IMPORTANCE_WEIGHTS),
                    difficulty=dict(DIFFICULTY_WEIGHTS),
                ),
            ),
        )

    def list_merge_decisions(
        self, session: Session, course_id: str
    ) -> KnowledgeMergeDecisionsResponse:
        version = self._require_active_framework(session, course_id)
        decisions = self.repository.list_merge_decisions(
            session, framework_version_id=version.id
        )
        return KnowledgeMergeDecisionsResponse(
            framework_version_id=version.id,
            decisions=[
                KnowledgeMergeDecisionResponse(
                    id=decision.id,
                    framework_version_id=decision.framework_version_id,
                    canonical_title=decision.canonical_title,
                    aliases=list(decision.aliases or []),
                    members=list(decision.members or []),
                    distinct_documents=decision.distinct_documents,
                    method=decision.method,
                    similarity=decision.similarity,
                    created_at=decision.created_at,
                )
                for decision in decisions
            ],
        )

    def add_alias_lock(
        self, session: Session, course_id: str, *, title_a: str, title_b: str
    ) -> KnowledgeAliasLockResponse:
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )
        first, second = _normalize_alias_pair(title_a, title_b)
        self.repository.add_alias_lock(
            session, course_id=course_id, title_a=first, title_b=second
        )
        session.commit()
        return KnowledgeAliasLockResponse(
            course_id=course_id, title_a=first, title_b=second
        )

    def delete_alias_lock(
        self, session: Session, course_id: str, *, title_a: str, title_b: str
    ) -> None:
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )
        first, second = _normalize_alias_pair(title_a, title_b)
        self.repository.delete_alias_lock(
            session, course_id=course_id, title_a=first, title_b=second
        )
        session.commit()

    def _score_framework(
        self, session: Session, version
    ) -> dict[str, LeafScore]:
        """把 active 版本的出处/关系/测验映射聚合成评分输入。"""
        leaf_nodes: list[KnowledgeNodeVersion] = []
        seen_leaf_ids: set[str] = set()
        for node in version.node_versions:
            if not node.is_leaf or node.knowledge_node_id in seen_leaf_ids:
                continue
            seen_leaf_ids.add(node.knowledge_node_id)
            leaf_nodes.append(node)
        source_pages = self.repository.count_source_pages_by_node(
            session, framework_version_id=version.id
        )
        source_documents = self.repository.count_source_documents_by_node(
            session, framework_version_id=version.id
        )
        question_counts = self.repository.count_question_mappings_by_node(
            session, framework_version_id=version.id
        )
        relations = [
            RelationEdge(source, target, relation_type)
            for source, target, relation_type in self.repository.list_version_relations(
                session, framework_version_id=version.id
            )
        ]
        return score_leaves(
            [
                LeafScoringInput(
                    node_version_id=node.id,
                    content_length=len(node.content or ""),
                    source_pages=source_pages.get(node.id, 0),
                    source_documents=source_documents.get(node.id, 0),
                    question_count=question_counts.get(node.id, 0),
                )
                for node in leaf_nodes
            ],
            relations,
        )

    def _section_paths(
        self, node_versions: list[KnowledgeNodeVersion]
    ) -> dict[str, list[str]]:
        """node_version_id → 从顶层章到自身的容器标题路径（不含课程根）。"""
        by_id = {node.id: node for node in node_versions}
        cache: dict[str, list[str]] = {}

        def build(node: KnowledgeNodeVersion) -> list[str]:
            cached = cache.get(node.id)
            if cached is not None:
                return cached
            titles: list[str] = []
            parent = by_id.get(node.parent_id) if node.parent_id else None
            while parent is not None and parent.level > 0:
                titles.append(parent.title)
                parent = by_id.get(parent.parent_id) if parent.parent_id else None
            titles.reverse()
            cache[node.id] = titles
            return titles

        for node in node_versions:
            build(node)
        return cache

    def _require_active_framework(self, session: Session, course_id: str):
        version = self.repository.get_active_framework(session, course_id)
        if version is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="No active knowledge framework exists for this course.",
                status_code=404,
                details={"course_id": course_id},
            )
        return version

    def _build_tree(
        self, node_versions: list[KnowledgeNodeVersion]
    ) -> list[KnowledgeTreeNodeResponse]:
        children_map: dict[str | None, list[KnowledgeNodeVersion]] = {}
        for node in self._dedupe_leaf_versions(node_versions):
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
