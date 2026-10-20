from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.knowledge import KnowledgeNodeVersion
from app.db.models.mastery import KnowledgeGap, StudentGapState
from app.db.models.quiz import Attempt, QuestionKnowledge
from app.repositories.mastery_repository import MasteryRepository
from app.schemas.mastery import (
    ChapterMasterySummaryResponse,
    KnowledgeGapResponse,
    MasteryStateResponse,
    MasteryOverviewResponse,
    ReviewTargetResponse,
    ReviewTargetsRequest,
    ReviewTargetsResponse,
)

MASTERY_ALGORITHM_VERSION = "beta-binomial-v1"
REVIEW_STRATEGY_VERSION = "weakness-exploration-v1"


@dataclass(frozen=True)
class AttemptEvidence:
    attempt: Attempt
    mapping: QuestionKnowledge
    normalized_score: float


class MasteryService:
    def __init__(self, repository: MasteryRepository | None = None) -> None:
        self.repository = repository or MasteryRepository()

    def apply_submission(self, session: Session, *, submission_id: str) -> None:
        submission = self.repository.get_submission(session, submission_id)
        if submission is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Quiz submission not found.",
                status_code=404,
                details={"submission_id": submission_id},
            )

        for evidence in self._collect_attempt_evidence(session, submission_id):
            self._apply_attempt_evidence(session, course_id=submission.quiz.course_id, evidence=evidence)

    def list_mastery(self, session: Session, course_id: str) -> list[MasteryStateResponse]:
        self._require_course(session, course_id)
        nodes = self.repository.list_current_framework_nodes(session, course_id)
        active_nodes = {node.knowledge_node_id: node for node in nodes}
        node_context = self._node_context(nodes)
        responses: list[MasteryStateResponse] = []
        for state in self.repository.list_states(session, course_id):
            node = active_nodes.get(state.knowledge_node_id)
            responses.append(
                MasteryStateResponse(
                    knowledge_node_id=state.knowledge_node_id,
                    title=node.title if node is not None else None,
                    node_version_id=node.id if node is not None else None,
                    parent_id=node.parent_id if node is not None else None,
                    section_path=self._section_path(node, node_context) if node is not None else [],
                    alpha=state.alpha,
                    beta=state.beta,
                    mastery_estimate=state.mastery_estimate,
                    evidence_count=state.evidence_count,
                    updated_at=state.updated_at,
                )
            )
        return responses

    def mastery_overview(self, session: Session, course_id: str) -> MasteryOverviewResponse:
        self._require_course(session, course_id)
        nodes = self.repository.list_current_framework_nodes(session, course_id)
        if not nodes:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="No active knowledge framework exists for this course.",
                status_code=404,
                details={"course_id": course_id},
            )
        context = self._node_context(nodes)
        states = {state.knowledge_node_id: state for state in self.repository.list_states(session, course_id)}
        summaries: list[ChapterMasterySummaryResponse] = []
        for chapter in (node for node in nodes if not node.is_leaf and node.parent_id is not None):
            leaves = [leaf for leaf in nodes if leaf.is_leaf and self._belongs_to(leaf, chapter, context)]
            if not leaves:
                continue
            tested = [states[leaf.knowledge_node_id] for leaf in leaves if leaf.knowledge_node_id in states]
            low = sum(1 for state in tested if state.mastery_estimate < 0.6)
            coverage = len(tested) / len(leaves)
            weak_density = low / len(tested) if tested else 0.0
            average = sum(state.mastery_estimate for state in tested) / len(tested) if tested else None
            priority = (1.0 - (average if average is not None else 0.5)) * 0.6
            priority += (1.0 - coverage) * 0.25 + weak_density * 0.15
            summaries.append(
                ChapterMasterySummaryResponse(
                    node_version_id=chapter.id,
                    title=chapter.title,
                    level=chapter.level,
                    section_path=self._section_path(chapter, context),
                    total_leaves=len(leaves),
                    tested_leaves=len(tested),
                    untested_leaves=len(leaves) - len(tested),
                    coverage=round(coverage, 6),
                    average_mastery=round(average, 6) if average is not None else None,
                    low_mastery_leaves=low,
                    weak_density=round(weak_density, 6),
                    priority=round(priority, 6),
                )
            )
        summaries.sort(key=lambda item: (-item.priority, item.node_version_id))
        return MasteryOverviewResponse(chapters=summaries)

    def list_wrongbook(self, session: Session, course_id: str) -> list[KnowledgeGapResponse]:
        self._require_course(session, course_id)
        context = self._node_context(self.repository.list_current_framework_nodes(session, course_id))
        return [self._gap_response(gap, context) for gap in self.repository.list_gaps(session, course_id)]

    def select_review_targets(
        self,
        session: Session,
        *,
        course_id: str,
        request: ReviewTargetsRequest,
    ) -> ReviewTargetsResponse:
        self._require_course(session, course_id)
        all_nodes = self.repository.list_current_framework_nodes(session, course_id)
        leaf_nodes = [node for node in all_nodes if node.is_leaf]
        if not leaf_nodes:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="No active knowledge framework exists for this course.",
                status_code=404,
                details={"course_id": course_id},
            )

        states_by_node = {
            state.knowledge_node_id: state for state in self.repository.list_states(session, course_id)
        }
        node_context = self._node_context(all_nodes)
        chapter_bonuses = self._chapter_bonuses(all_nodes, states_by_node)
        weakness_targets: list[ReviewTargetResponse] = []
        exploration_targets: list[ReviewTargetResponse] = []
        for node in leaf_nodes:
            state = states_by_node.get(node.knowledge_node_id)
            target = self._score_target(node, state, node_context, chapter_bonuses)
            if state is None:
                exploration_targets.append(target)
            else:
                weakness_targets.append(target)
        weakness_targets.sort(key=lambda target: target.priority, reverse=True)
        exploration_targets.sort(key=lambda target: target.title)
        exploration_limit = min(
            len(exploration_targets),
            round(request.limit * request.exploration_ratio),
        )
        weakness_limit = request.limit - exploration_limit
        selected = [
            *weakness_targets[:weakness_limit],
            *exploration_targets[:exploration_limit],
        ]
        if len(selected) < request.limit:
            selected_ids = {target.knowledge_node_id for target in selected}
            remaining = [
                target
                for target in [*weakness_targets, *exploration_targets]
                if target.knowledge_node_id not in selected_ids
            ]
            selected.extend(remaining[: request.limit - len(selected)])
        log = self.repository.add_review_strategy_log(
            session,
            course_id=course_id,
            selected_targets_json=[target.model_dump() for target in selected],
            strategy_version=REVIEW_STRATEGY_VERSION,
            rationale_json={
                "limit": request.limit,
                "exploration_ratio": request.exploration_ratio,
                "rule": "Prioritize low mastery while keeping untested leaves visible.",
                "chapter_aggregation": "Chapter priority combines weakness, coverage, and weak-leaf density; leaf evidence remains authoritative.",
            },
        )
        session.commit()
        return ReviewTargetsResponse(
            strategy_log_id=log.id,
            strategy_version=REVIEW_STRATEGY_VERSION,
            targets=selected,
        )

    def _collect_attempt_evidence(
        self,
        session: Session,
        submission_id: str,
    ) -> list[AttemptEvidence]:
        evidence: list[AttemptEvidence] = []
        attempts = self.repository.list_submission_attempts(session, submission_id)
        for attempt in attempts:
            if attempt.max_score <= 0:
                continue
            primary_mappings = [
                mapping
                for mapping in attempt.question.knowledge_mappings
                if mapping.relation_role == "primary"
            ]
            normalized_score = max(0.0, min(1.0, attempt.score / attempt.max_score))
            for mapping in primary_mappings:
                evidence.append(
                    AttemptEvidence(
                        attempt=attempt,
                        mapping=mapping,
                        normalized_score=normalized_score,
                    )
                )
        return evidence

    def _apply_attempt_evidence(
        self,
        session: Session,
        *,
        course_id: str,
        evidence: AttemptEvidence,
    ) -> None:
        node_version = evidence.mapping.node_version
        state = self.repository.get_or_create_state(
            session,
            course_id=course_id,
            knowledge_node_id=node_version.knowledge_node_id,
        )
        if self.repository.mastery_event_exists(
            session,
            state_id=state.id,
            attempt_id=evidence.attempt.id,
        ):
            return

        delta_alpha = evidence.normalized_score * evidence.mapping.weight
        delta_beta = (1.0 - evidence.normalized_score) * evidence.mapping.weight
        old_estimate = state.mastery_estimate
        state.alpha += delta_alpha
        state.beta += delta_beta
        state.evidence_count += 1
        state.mastery_estimate = state.alpha / (state.alpha + state.beta)
        self.repository.add_mastery_event(
            session,
            state_id=state.id,
            attempt_id=evidence.attempt.id,
            evidence_type=self._mastery_evidence_type(evidence.normalized_score),
            delta_alpha=delta_alpha,
            delta_beta=delta_beta,
            old_estimate=old_estimate,
            new_estimate=state.mastery_estimate,
            algorithm_version=MASTERY_ALGORITHM_VERSION,
        )
        self._update_gap(session, course_id=course_id, node_version=node_version, evidence=evidence)

    def _update_gap(
        self,
        session: Session,
        *,
        course_id: str,
        node_version: KnowledgeNodeVersion,
        evidence: AttemptEvidence,
    ) -> None:
        if evidence.normalized_score < 0.7:
            gap = self.repository.get_or_create_gap(
                session,
                course_id=course_id,
                node_version_id=node_version.id,
                gap_type="low_score",
            )
        else:
            gap = self.repository.get_gap(
                session,
                course_id=course_id,
                node_version_id=node_version.id,
                gap_type="low_score",
            )
            if gap is None:
                return
        summary = dict(gap.evidence_summary_json or {})
        total = int(summary.get("total_evidence", 0)) + 1
        incorrect = int(summary.get("low_score_evidence", 0))
        positive = int(summary.get("positive_evidence", 0))
        if evidence.normalized_score < 0.7:
            incorrect += 1
            strength = 1.0 - evidence.normalized_score
            self.repository.add_gap_evidence(
                session,
                attempt_id=evidence.attempt.id,
                gap_id=gap.id,
                evidence_type="low_score",
                strength=strength,
                rationale="Primary knowledge point received a score below the configured threshold.",
            )
        else:
            positive += 1

        confidence = incorrect / total if total else 0.0
        gap.confidence = confidence
        gap.evidence_summary_json = {
            "total_evidence": total,
            "low_score_evidence": incorrect,
            "positive_evidence": positive,
            "last_attempt_id": evidence.attempt.id,
            "last_normalized_score": evidence.normalized_score,
        }
        if incorrect == 0:
            gap.status = "uncertain"
        elif positive > 0 and evidence.normalized_score >= 0.7:
            gap.status = "improving"
        elif incorrect >= 2 and confidence >= 0.5:
            gap.status = "confirmed"
        else:
            gap.status = "suspected"

    def _score_target(
        self,
        node: KnowledgeNodeVersion,
        state: StudentGapState | None,
        node_context: dict[str, KnowledgeNodeVersion],
        chapter_bonuses: dict[str, float],
    ) -> ReviewTargetResponse:
        bonus = chapter_bonuses.get(self._chapter_key(node, node_context), 0.0)
        if state is None:
            return ReviewTargetResponse(
                knowledge_node_id=node.knowledge_node_id,
                node_version_id=node.id,
                title=node.title,
                section_path=self._section_path(node, node_context),
                priority=round(1.15 + bonus, 6),
                mastery_estimate=None,
                evidence_count=0,
                reason="exploration_untested",
            )
        uncertainty_bonus = 0.2 if state.evidence_count < 2 else 0.0
        priority = (1.0 - state.mastery_estimate) + uncertainty_bonus
        return ReviewTargetResponse(
            knowledge_node_id=node.knowledge_node_id,
            node_version_id=node.id,
            title=node.title,
            section_path=self._section_path(node, node_context),
            priority=round(priority + bonus, 6),
            mastery_estimate=state.mastery_estimate,
            evidence_count=state.evidence_count,
            reason="weak_mastery" if state.mastery_estimate < 0.6 else "coverage_check",
        )

    def _gap_response(
        self, gap: KnowledgeGap, node_context: dict[str, KnowledgeNodeVersion]
    ) -> KnowledgeGapResponse:
        return KnowledgeGapResponse(
            gap_id=gap.id,
            knowledge_node_id=gap.node_version.knowledge_node_id,
            node_version_id=gap.node_version_id,
            title=gap.node_version.title,
            section_path=self._section_path(gap.node_version, node_context),
            gap_type=gap.gap_type,
            status=gap.status,
            confidence=gap.confidence,
            evidence_count=len(gap.evidence),
            evidence_summary=gap.evidence_summary_json,
            updated_at=gap.updated_at,
        )

    def _node_context(self, nodes: list[KnowledgeNodeVersion]) -> dict[str, KnowledgeNodeVersion]:
        return {node.id: node for node in nodes}

    def _section_path(
        self, node: KnowledgeNodeVersion, nodes: dict[str, KnowledgeNodeVersion]
    ) -> list[str]:
        path: list[str] = []
        current: KnowledgeNodeVersion | None = node
        while current is not None and current.parent_id is not None:
            path.append(current.title)
            current = nodes.get(current.parent_id)
        if path:
            # The leaf itself is not a section; the remaining titles are its
            # container path below the synthetic root node.
            path.pop(0)
        return list(reversed(path))

    def _belongs_to(
        self,
        leaf: KnowledgeNodeVersion,
        ancestor: KnowledgeNodeVersion,
        nodes: dict[str, KnowledgeNodeVersion],
    ) -> bool:
        current = leaf
        while current.parent_id is not None:
            if current.parent_id == ancestor.id:
                return True
            current = nodes.get(current.parent_id)
            if current is None:
                return False
        return False

    def _chapter_key(
        self, node: KnowledgeNodeVersion, nodes: dict[str, KnowledgeNodeVersion]
    ) -> str:
        current = node
        while current.parent_id is not None:
            parent = nodes.get(current.parent_id)
            if parent is None or parent.parent_id is None:
                return parent.id if parent is not None else current.id
            current = parent
        return current.id

    def _chapter_bonuses(
        self,
        nodes: list[KnowledgeNodeVersion],
        states: dict[str, StudentGapState],
    ) -> dict[str, float]:
        context = self._node_context(nodes)
        chapters = [node for node in nodes if not node.is_leaf and node.parent_id is not None]
        bonuses: dict[str, float] = {}
        for chapter in chapters:
            leaves = [leaf for leaf in nodes if leaf.is_leaf and self._belongs_to(leaf, chapter, context)]
            if not leaves:
                continue
            tested = [states[leaf.knowledge_node_id] for leaf in leaves if leaf.knowledge_node_id in states]
            average = sum(state.mastery_estimate for state in tested) / len(tested) if tested else 0.5
            coverage = len(tested) / len(leaves)
            weak_density = sum(1 for state in tested if state.mastery_estimate < 0.6) / len(tested) if tested else 0.0
            bonuses[chapter.id] = round((1.0 - average) * 0.08 + (1.0 - coverage) * 0.04 + weak_density * 0.03, 6)
        return bonuses

    def _require_course(self, session: Session, course_id: str) -> None:
        if self.repository.get_course(session, course_id) is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )

    def _mastery_evidence_type(self, normalized_score: float) -> str:
        if normalized_score >= 0.999:
            return "correct"
        if normalized_score <= 0.001:
            return "incorrect"
        return "partial"
