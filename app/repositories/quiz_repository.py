from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.course import Course
from app.db.models.document import Document
from app.db.models.knowledge import KnowledgeFrameworkVersion, KnowledgeNodeVersion, KnowledgeSource
from app.db.models.mastery import KnowledgeGap, StudentGapState
from app.db.models.quiz import (
    Attempt,
    Question,
    QuestionGenerationRun,
    QuestionKnowledge,
    Quiz,
    QuizQuestion,
    QuizSubmission,
)


class QuizRepository:
    def get_course(self, session: Session, course_id: str) -> Course | None:
        return session.get(Course, course_id)

    def get_active_framework(
        self, session: Session, course_id: str
    ) -> KnowledgeFrameworkVersion | None:
        statement = (
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .where(KnowledgeFrameworkVersion.status == "active")
            .options(selectinload(KnowledgeFrameworkVersion.node_versions))
            .order_by(KnowledgeFrameworkVersion.version_number.desc())
            .limit(1)
        )
        return session.scalar(statement)

    def get_framework_version(
        self, session: Session, framework_version_id: str
    ) -> KnowledgeFrameworkVersion | None:
        statement = (
            select(KnowledgeFrameworkVersion)
            .where(KnowledgeFrameworkVersion.id == framework_version_id)
            .options(selectinload(KnowledgeFrameworkVersion.node_versions))
        )
        return session.scalar(statement)

    def list_ready_documents(self, session: Session, course_id: str) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.course_id == course_id)
            .where(Document.status.in_(["completed", "completed_with_warnings"]))
            .options(selectinload(Document.pages), selectinload(Document.chunks))
            .order_by(Document.created_at.asc())
        )
        return list(session.scalars(statement))

    def create_quiz(
        self,
        session: Session,
        *,
        course_id: str,
        framework_version_id: str,
        status: str,
        settings_json: dict,
    ) -> Quiz:
        quiz = Quiz(
            course_id=course_id,
            framework_version_id=framework_version_id,
            status=status,
            settings_json=settings_json,
        )
        session.add(quiz)
        session.flush()
        session.refresh(quiz)
        return quiz

    def get_quiz(self, session: Session, quiz_id: str) -> Quiz | None:
        statement = (
            select(Quiz)
            .where(Quiz.id == quiz_id)
            .options(
                selectinload(Quiz.quiz_questions),
                selectinload(Quiz.submissions),
                selectinload(Quiz.generation_runs),
            )
        )
        return session.scalar(statement)

    def get_quiz_with_attempts(self, session: Session, quiz_id: str) -> Quiz | None:
        statement = (
            select(Quiz)
            .where(Quiz.id == quiz_id)
            .options(
                selectinload(Quiz.quiz_questions),
                selectinload(Quiz.submissions).selectinload(QuizSubmission.attempts),
            )
        )
        return session.scalar(statement)

    def list_existing_question_hashes(self, session: Session, course_id: str) -> set[str]:
        statement = select(Question.content_hash).where(Question.course_id == course_id)
        return set(session.scalars(statement))

    def list_recent_question_stems(
        self, session: Session, course_id: str, *, limit: int = 20
    ) -> list[str]:
        statement = (
            select(Question.stem)
            .where(Question.course_id == course_id)
            .order_by(Question.created_at.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

    def get_knowledge_selection_stats(
        self, session: Session, *, course_id: str
    ) -> dict[str, dict[str, float | int]]:
        statement = (
            select(
                KnowledgeNodeVersion.knowledge_node_id,
                func.count(func.distinct(QuestionKnowledge.question_id)).label("question_count"),
                func.count(func.distinct(Attempt.id)).label("attempt_count"),
                func.count(
                    func.distinct(
                        case((Attempt.score < Attempt.max_score, Attempt.id), else_=None)
                    )
                ).label("wrong_count"),
            )
            .join(
                QuestionKnowledge,
                QuestionKnowledge.node_version_id == KnowledgeNodeVersion.id,
            )
            .join(Question, Question.id == QuestionKnowledge.question_id)
            .outerjoin(Attempt, Attempt.question_id == Question.id)
            .where(Question.course_id == course_id)
            .where(QuestionKnowledge.relation_role == "primary")
            .group_by(KnowledgeNodeVersion.knowledge_node_id)
        )
        stats = {
            node_id: {
                "question_count": int(question_count or 0),
                "attempt_count": int(attempt_count or 0),
                "wrong_count": int(wrong_count or 0),
            }
            for node_id, question_count, attempt_count, wrong_count in session.execute(statement)
        }

        state_statement = select(
            StudentGapState.knowledge_node_id,
            StudentGapState.mastery_estimate,
            StudentGapState.evidence_count,
        ).where(StudentGapState.course_id == course_id)
        for node_id, mastery_estimate, evidence_count in session.execute(state_statement):
            stats.setdefault(node_id, {}).update(
                mastery_estimate=float(mastery_estimate),
                evidence_count=int(evidence_count),
            )

        gap_statement = (
            select(
                KnowledgeNodeVersion.knowledge_node_id,
                func.max(KnowledgeGap.confidence),
            )
            .join(KnowledgeGap, KnowledgeGap.node_version_id == KnowledgeNodeVersion.id)
            .where(KnowledgeGap.course_id == course_id)
            .where(KnowledgeGap.status.in_(["suspected", "confirmed", "uncertain"]))
            .group_by(KnowledgeNodeVersion.knowledge_node_id)
        )
        for node_id, confidence in session.execute(gap_statement):
            stats.setdefault(node_id, {}).update(gap_confidence=float(confidence or 0.0))
        return stats

    def create_generation_run(
        self,
        session: Session,
        *,
        quiz_id: str,
        prompt_version: str,
        model_name: str,
        input_summary_json: dict,
        output_summary_json: dict,
        status: str,
        error_code: str | None = None,
    ) -> QuestionGenerationRun:
        run = QuestionGenerationRun(
            quiz_id=quiz_id,
            prompt_version=prompt_version,
            model_name=model_name,
            input_summary_json=input_summary_json,
            output_summary_json=output_summary_json,
            status=status,
            error_code=error_code,
        )
        session.add(run)
        session.flush()
        session.refresh(run)
        return run

    def create_question(
        self,
        session: Session,
        *,
        course_id: str,
        question_type: str,
        stem: str,
        options_json: list[dict] | None,
        answer_key_json: dict | None,
        rubric_json: dict | None,
        explanation: str | None,
        difficulty: str,
        source_metadata_json: dict,
        content_hash: str,
    ) -> Question:
        question = Question(
            course_id=course_id,
            type=question_type,
            stem=stem,
            options_json=options_json,
            answer_key_json=answer_key_json,
            rubric_json=rubric_json,
            explanation=explanation,
            difficulty=difficulty,
            source_metadata_json=source_metadata_json,
            content_hash=content_hash,
        )
        session.add(question)
        session.flush()
        session.refresh(question)
        return question

    def add_question_mapping(
        self,
        session: Session,
        *,
        question_id: str,
        node_version_id: str,
        relation_role: str,
        weight: float,
    ) -> QuestionKnowledge:
        mapping = QuestionKnowledge(
            question_id=question_id,
            node_version_id=node_version_id,
            relation_role=relation_role,
            weight=weight,
        )
        session.add(mapping)
        session.flush()
        return mapping

    def add_quiz_question(
        self,
        session: Session,
        *,
        quiz_id: str,
        question_id: str,
        ordinal: int,
        question_snapshot_json: dict,
    ) -> QuizQuestion:
        quiz_question = QuizQuestion(
            quiz_id=quiz_id,
            question_id=question_id,
            ordinal=ordinal,
            question_snapshot_json=question_snapshot_json,
        )
        session.add(quiz_question)
        session.flush()
        return quiz_question

    def find_submission_by_idempotency_key(
        self, session: Session, *, quiz_id: str, idempotency_key: str
    ) -> QuizSubmission | None:
        statement = (
            select(QuizSubmission)
            .where(QuizSubmission.quiz_id == quiz_id)
            .where(QuizSubmission.idempotency_key == idempotency_key)
            .options(selectinload(QuizSubmission.attempts))
        )
        return session.scalar(statement)

    def create_submission(
        self,
        session: Session,
        *,
        quiz_id: str,
        idempotency_key: str,
        request_hash: str,
        response_json: dict,
    ) -> QuizSubmission:
        submission = QuizSubmission(
            quiz_id=quiz_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_json=response_json,
        )
        session.add(submission)
        session.flush()
        session.refresh(submission)
        return submission

    def add_attempt(
        self,
        session: Session,
        *,
        submission_id: str,
        quiz_id: str,
        question_id: str,
        idempotency_key: str,
        submitted_answer_json: dict,
        score: float,
        max_score: float,
        grading_method: str,
        feedback_json: dict,
    ) -> Attempt:
        attempt = Attempt(
            submission_id=submission_id,
            quiz_id=quiz_id,
            question_id=question_id,
            idempotency_key=idempotency_key,
            submitted_answer_json=submitted_answer_json,
            score=score,
            max_score=max_score,
            grading_method=grading_method,
            feedback_json=feedback_json,
        )
        session.add(attempt)
        session.flush()
        return attempt

    def count_quiz_attempts(self, session: Session, quiz_id: str) -> int:
        return int(
            session.scalar(select(func.count(Attempt.id)).where(Attempt.quiz_id == quiz_id)) or 0
        )

    def get_node_versions_for_framework(
        self,
        session: Session,
        *,
        framework_version_id: str,
        knowledge_node_ids: list[str] | None = None,
    ) -> list[KnowledgeNodeVersion]:
        statement = (
            select(KnowledgeNodeVersion)
            .where(KnowledgeNodeVersion.framework_version_id == framework_version_id)
            .options(
                selectinload(KnowledgeNodeVersion.sources).selectinload(KnowledgeSource.document),
                selectinload(KnowledgeNodeVersion.sources).selectinload(KnowledgeSource.chunk),
            )
            .order_by(KnowledgeNodeVersion.level.asc(), KnowledgeNodeVersion.sort_order.asc())
        )
        if knowledge_node_ids:
            statement = statement.where(KnowledgeNodeVersion.knowledge_node_id.in_(knowledge_node_ids))
        return list(session.scalars(statement))
