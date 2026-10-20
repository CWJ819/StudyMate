from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.course import Course
from app.db.models.knowledge import KnowledgeFrameworkVersion, KnowledgeNodeVersion
from app.db.models.mastery import (
    AttemptGapEvidence,
    KnowledgeGap,
    MasteryEvent,
    ReviewStrategyLog,
    StudentGapState,
)
from app.db.models.quiz import Attempt, Question, QuestionKnowledge, QuizSubmission


class MasteryRepository:
    def get_course(self, session: Session, course_id: str) -> Course | None:
        return session.get(Course, course_id)

    def list_submission_attempts(self, session: Session, submission_id: str) -> list[Attempt]:
        statement = (
            select(Attempt)
            .where(Attempt.submission_id == submission_id)
            .options(
                selectinload(Attempt.question)
                .selectinload(Question.knowledge_mappings)
                .selectinload(QuestionKnowledge.node_version)
            )
            .order_by(Attempt.submitted_at.asc())
        )
        return list(session.scalars(statement))

    def get_submission(self, session: Session, submission_id: str) -> QuizSubmission | None:
        return session.get(QuizSubmission, submission_id)

    def get_or_create_state(
        self,
        session: Session,
        *,
        course_id: str,
        knowledge_node_id: str,
    ) -> StudentGapState:
        statement = (
            select(StudentGapState)
            .where(StudentGapState.course_id == course_id)
            .where(StudentGapState.knowledge_node_id == knowledge_node_id)
        )
        state = session.scalar(statement)
        if state is not None:
            return state
        state = StudentGapState(
            course_id=course_id,
            knowledge_node_id=knowledge_node_id,
            alpha=2.0,
            beta=2.0,
            mastery_estimate=0.5,
            evidence_count=0,
            updated_at=datetime.now(UTC),
        )
        session.add(state)
        session.flush()
        session.refresh(state)
        return state

    def mastery_event_exists(self, session: Session, *, state_id: str, attempt_id: str) -> bool:
        return (
            session.scalar(
                select(MasteryEvent.id)
                .where(MasteryEvent.state_id == state_id)
                .where(MasteryEvent.attempt_id == attempt_id)
                .limit(1)
            )
            is not None
        )

    def add_mastery_event(
        self,
        session: Session,
        *,
        state_id: str,
        attempt_id: str,
        evidence_type: str,
        delta_alpha: float,
        delta_beta: float,
        old_estimate: float,
        new_estimate: float,
        algorithm_version: str,
    ) -> MasteryEvent:
        event = MasteryEvent(
            state_id=state_id,
            attempt_id=attempt_id,
            evidence_type=evidence_type,
            delta_alpha=delta_alpha,
            delta_beta=delta_beta,
            old_estimate=old_estimate,
            new_estimate=new_estimate,
            algorithm_version=algorithm_version,
        )
        session.add(event)
        session.flush()
        return event

    def get_or_create_gap(
        self,
        session: Session,
        *,
        course_id: str,
        node_version_id: str,
        gap_type: str,
    ) -> KnowledgeGap:
        statement = (
            select(KnowledgeGap)
            .where(KnowledgeGap.course_id == course_id)
            .where(KnowledgeGap.node_version_id == node_version_id)
            .where(KnowledgeGap.gap_type == gap_type)
        )
        gap = session.scalar(statement)
        if gap is not None:
            return gap
        gap = KnowledgeGap(
            course_id=course_id,
            node_version_id=node_version_id,
            gap_type=gap_type,
            status="suspected",
            confidence=0.0,
            evidence_summary_json={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(gap)
        session.flush()
        session.refresh(gap)
        return gap

    def get_gap(
        self,
        session: Session,
        *,
        course_id: str,
        node_version_id: str,
        gap_type: str,
    ) -> KnowledgeGap | None:
        statement = (
            select(KnowledgeGap)
            .where(KnowledgeGap.course_id == course_id)
            .where(KnowledgeGap.node_version_id == node_version_id)
            .where(KnowledgeGap.gap_type == gap_type)
        )
        return session.scalar(statement)

    def add_gap_evidence(
        self,
        session: Session,
        *,
        attempt_id: str,
        gap_id: str,
        evidence_type: str,
        strength: float,
        rationale: str,
    ) -> AttemptGapEvidence:
        evidence = AttemptGapEvidence(
            attempt_id=attempt_id,
            gap_id=gap_id,
            evidence_type=evidence_type,
            strength=strength,
            rationale=rationale,
        )
        session.add(evidence)
        session.flush()
        return evidence

    def list_states(self, session: Session, course_id: str) -> list[StudentGapState]:
        statement = (
            select(StudentGapState)
            .where(StudentGapState.course_id == course_id)
            .options(selectinload(StudentGapState.knowledge_node))
            .order_by(StudentGapState.mastery_estimate.asc())
        )
        return list(session.scalars(statement))

    def list_active_leaf_nodes(self, session: Session, course_id: str) -> list[KnowledgeNodeVersion]:
        active_statement = (
            select(KnowledgeFrameworkVersion.id)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .where(KnowledgeFrameworkVersion.status == "active")
            .order_by(KnowledgeFrameworkVersion.version_number.desc())
            .limit(1)
        )
        active_id = session.scalar(active_statement)
        if active_id is None:
            return []
        statement = (
            select(KnowledgeNodeVersion)
            .where(KnowledgeNodeVersion.framework_version_id == active_id)
            .where(KnowledgeNodeVersion.is_leaf.is_(True))
            .order_by(KnowledgeNodeVersion.level.asc(), KnowledgeNodeVersion.sort_order.asc())
        )
        return list(session.scalars(statement))

    def list_gaps(self, session: Session, course_id: str) -> list[KnowledgeGap]:
        statement = (
            select(KnowledgeGap)
            .where(KnowledgeGap.course_id == course_id)
            .options(
                selectinload(KnowledgeGap.node_version),
                selectinload(KnowledgeGap.evidence),
            )
            .order_by(KnowledgeGap.confidence.desc(), KnowledgeGap.updated_at.desc())
        )
        return list(session.scalars(statement))

    def add_review_strategy_log(
        self,
        session: Session,
        *,
        course_id: str,
        selected_targets_json: list[dict],
        strategy_version: str,
        rationale_json: dict,
    ) -> ReviewStrategyLog:
        log = ReviewStrategyLog(
            course_id=course_id,
            selected_targets_json=selected_targets_json,
            strategy_version=strategy_version,
            rationale_json=rationale_json,
        )
        session.add(log)
        session.flush()
        session.refresh(log)
        return log
