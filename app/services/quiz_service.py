from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.llm.base import LLMTemporaryError
from app.llm.openai_compatible import get_llm_adapter
from app.llm.prompts.quiz_generation import SYSTEM_PROMPT as QUIZ_GENERATION_SYSTEM_PROMPT
from app.llm.prompts.short_answer_grading import (
    SYSTEM_PROMPT as SHORT_ANSWER_GRADING_SYSTEM_PROMPT,
)
from app.llm.schemas import (
    QuestionKnowledgeMappingCandidate,
    QuestionOptionCandidate,
    QuizGenerationCandidate,
    QuizQuestionCandidate,
    RubricCriterionCandidate,
    ShortAnswerGradingCandidate,
    ShortAnswerRubricCandidate,
)
from app.repositories.job_repository import JobRepository
from app.repositories.llm_repository import LLMRepository
from app.repositories.quiz_repository import QuizRepository
from app.schemas.quiz import (
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_SINGLE_CHOICE,
    QUIZ_STATUS_BUILDING,
    QUIZ_STATUS_FAILED,
    QUIZ_STATUS_OPEN,
    QUIZ_STATUS_SUBMITTED,
    QuestionKnowledgeMappingSnapshot,
    QuestionRubric,
    QuizAnswerInput,
    QuizDetailResponse,
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizQuestionOption,
    QuizQuestionResponse,
    QuizQuestionResultResponse,
    QuizQuestionSnapshot,
    QuizSubmitRequest,
    QuizSubmitResponse,
)
from app.services.mastery_service import MasteryService

QUIZ_GENERATION_PROMPT_VERSION = "quiz-generation-v3"
QUIZ_CONTEXT_NODE_LIMIT = 36
QUIZ_SOURCE_CONTEXT_CHAR_LIMIT = 24000
REVIEW_QUESTION_RATIO = 0.4
SHORT_ANSWER_GRADING_PROMPT_VERSION = "short-answer-grading-v1"


class QuizGeneratePayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quiz_id: str
    course_id: str


@dataclass(frozen=True)
class PreparedQuestion:
    question_type: str
    stem: str
    options_json: list[dict] | None
    answer_key_json: dict | None
    rubric_json: dict | None
    explanation: str | None
    difficulty: str
    source_metadata_json: dict[str, Any]
    content_hash: str
    snapshot: QuizQuestionSnapshot


class QuizService:
    def __init__(
        self,
        repository: QuizRepository | None = None,
        job_repository: JobRepository | None = None,
        llm_repository: LLMRepository | None = None,
    ) -> None:
        self.repository = repository or QuizRepository()
        self.job_repository = job_repository or JobRepository()
        self.llm_repository = llm_repository or LLMRepository()

    def start_generate(
        self,
        session: Session,
        *,
        course_id: str,
        request: QuizGenerateRequest,
    ) -> QuizGenerateResponse:
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )

        framework = self.repository.get_active_framework(session, course_id)
        if framework is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="No active knowledge framework exists for this course.",
                status_code=404,
                details={"course_id": course_id},
            )

        ready_documents = self.repository.list_ready_documents(session, course_id)
        if not ready_documents:
            raise AppError(
                code="MATERIALS_NOT_READY",
                message="At least one parsed material is required before generating a quiz.",
                status_code=400,
            )

        self._validate_requested_scope(framework.node_versions, request.knowledge_node_ids)
        adapter = get_llm_adapter()
        adapter.ensure_available()

        quiz = self.repository.create_quiz(
            session,
            course_id=course_id,
            framework_version_id=framework.id,
            status=QUIZ_STATUS_BUILDING,
            settings_json=request.model_dump(),
        )
        job = self.job_repository.create_job(
            session,
            job_type="quiz.generate",
            payload_json=QuizGeneratePayloadModel(quiz_id=quiz.id, course_id=course_id).model_dump(),
            max_attempts=2,
        )
        session.commit()
        return QuizGenerateResponse(quiz_id=quiz.id, job_id=job.id, status=quiz.status)

    def generate_quiz_job(self, session: Session, *, course_id: str, quiz_id: str) -> None:
        quiz = self.repository.get_quiz(session, quiz_id)
        if quiz is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Quiz not found.",
                status_code=404,
                details={"quiz_id": quiz_id},
            )
        if quiz.status == QUIZ_STATUS_OPEN:
            return

        framework = self.repository.get_framework_version(session, quiz.framework_version_id)
        if framework is None or framework.course_id != course_id:
            quiz.status = QUIZ_STATUS_FAILED
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Knowledge framework version not found for quiz generation.",
                status_code=404,
            )

        ready_documents = self.repository.list_ready_documents(session, course_id)
        if not ready_documents:
            quiz.status = QUIZ_STATUS_FAILED
            raise AppError(
                code="MATERIALS_NOT_READY",
                message="Parsed materials are required before generating a quiz.",
                status_code=400,
            )

        settings = QuizGenerateRequest.model_validate(quiz.settings_json)
        node_versions = self.repository.get_node_versions_for_framework(
            session,
            framework_version_id=framework.id,
            knowledge_node_ids=settings.knowledge_node_ids or None,
        )
        if not node_versions:
            quiz.status = QUIZ_STATUS_FAILED
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Requested knowledge nodes do not exist in the quiz framework version.",
                status_code=404,
            )
        leaf_nodes = [node for node in node_versions if node.is_leaf] or node_versions
        selection_stats = self.repository.get_knowledge_selection_stats(
            session, course_id=course_id
        )
        selected_nodes, selection_roles = self._select_generation_nodes(
            quiz_id=quiz.id,
            settings=settings,
            nodes=leaf_nodes,
            selection_stats=selection_stats,
        )
        node_versions_by_knowledge_id = {
            node.knowledge_node_id: node for node in selected_nodes
        }
        existing_hashes = self.repository.list_existing_question_hashes(session, course_id)
        prior_stems = self.repository.list_recent_question_stems(session, course_id)

        try:
            prepared_questions = self._generate_questions_with_dedup(
                session,
                quiz_id=quiz.id,
                course_id=course_id,
                course_name=self.repository.get_course(session, course_id).name,  # type: ignore[union-attr]
                settings=settings,
                node_versions=selected_nodes,
                selection_roles=selection_roles,
                node_versions_by_knowledge_id=node_versions_by_knowledge_id,
                ready_documents=ready_documents,
                existing_hashes=existing_hashes,
                prior_stems=prior_stems,
            )
        except (AppError, LLMTemporaryError):
            quiz.status = QUIZ_STATUS_FAILED
            raise

        for ordinal, prepared_question in enumerate(prepared_questions, start=1):
            question = self.repository.create_question(
                session,
                course_id=course_id,
                question_type=prepared_question.question_type,
                stem=prepared_question.stem,
                options_json=prepared_question.options_json,
                answer_key_json=prepared_question.answer_key_json,
                rubric_json=prepared_question.rubric_json,
                explanation=prepared_question.explanation,
                difficulty=prepared_question.difficulty,
                source_metadata_json=prepared_question.source_metadata_json,
                content_hash=prepared_question.content_hash,
            )
            for mapping in prepared_question.snapshot.knowledge_mappings:
                self.repository.add_question_mapping(
                    session,
                    question_id=question.id,
                    node_version_id=mapping.node_version_id,
                    relation_role=mapping.relation_role,
                    weight=mapping.weight,
                )
            snapshot = prepared_question.snapshot.model_copy(update={"question_id": question.id})
            self.repository.add_quiz_question(
                session,
                quiz_id=quiz.id,
                question_id=question.id,
                ordinal=ordinal,
                question_snapshot_json=snapshot.model_dump(),
            )
        quiz.status = QUIZ_STATUS_OPEN

    def get_quiz(self, session: Session, quiz_id: str) -> QuizDetailResponse:
        quiz = self.repository.get_quiz(session, quiz_id)
        if quiz is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Quiz not found.",
                status_code=404,
                details={"quiz_id": quiz_id},
            )
        questions = [
            self._to_public_question_response(quiz_question.ordinal, quiz_question.question_snapshot_json)
            for quiz_question in sorted(quiz.quiz_questions, key=lambda item: item.ordinal)
        ]
        return QuizDetailResponse(
            quiz_id=quiz.id,
            course_id=quiz.course_id,
            framework_version_id=quiz.framework_version_id,
            status=quiz.status,
            created_at=quiz.created_at,
            questions=questions,
        )

    def submit_quiz(
        self,
        session: Session,
        *,
        quiz_id: str,
        request: QuizSubmitRequest,
    ) -> QuizSubmitResponse:
        quiz = self.repository.get_quiz_with_attempts(session, quiz_id)
        if quiz is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Quiz not found.",
                status_code=404,
                details={"quiz_id": quiz_id},
            )

        request_hash = self._hash_payload(request.model_dump())
        existing_submission = self.repository.find_submission_by_idempotency_key(
            session,
            quiz_id=quiz_id,
            idempotency_key=request.idempotency_key,
        )
        if existing_submission is not None:
            if existing_submission.request_hash != request_hash:
                raise AppError(
                    code="IDEMPOTENCY_CONFLICT",
                    message="The same idempotency key was already used for a different quiz submission request.",
                    status_code=409,
                    details={"quiz_id": quiz_id},
                )
            return QuizSubmitResponse.model_validate(existing_submission.response_json)

        if quiz.status != QUIZ_STATUS_OPEN:
            raise AppError(
                code="QUIZ_NOT_OPEN",
                message="This quiz is not open for submission.",
                status_code=409,
                details={"quiz_id": quiz_id, "status": quiz.status},
            )
        if quiz.submissions or self.repository.count_quiz_attempts(session, quiz_id) > 0:
            raise AppError(
                code="QUIZ_ALREADY_SUBMITTED",
                message="This quiz has already been submitted.",
                status_code=409,
                details={"quiz_id": quiz_id},
            )

        answers_by_question_id = self._validate_submission_shape(quiz, request.answers)
        question_results: list[QuizQuestionResultResponse] = []
        raw_attempts: list[tuple[QuizQuestionSnapshot, QuizAnswerInput, QuizQuestionResultResponse, dict]] = []

        for quiz_question in sorted(quiz.quiz_questions, key=lambda item: item.ordinal):
            snapshot = QuizQuestionSnapshot.model_validate(quiz_question.question_snapshot_json)
            answer = answers_by_question_id[snapshot.question_id]
            result, feedback_json = self._grade_answer(snapshot, answer)
            question_results.append(result)
            raw_attempts.append((snapshot, answer, result, feedback_json))

        total_score = float(sum(result.score for result in question_results))
        max_score = float(sum(result.max_score for result in question_results))
        response = QuizSubmitResponse(
            submission_id="pending",
            quiz_id=quiz_id,
            status=QUIZ_STATUS_SUBMITTED,
            total_score=total_score,
            max_score=max_score,
            question_results=question_results,
        )
        submission = self.repository.create_submission(
            session,
            quiz_id=quiz_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            response_json=response.model_dump(),
        )
        for snapshot, answer, result, feedback_json in raw_attempts:
            submitted_answer_json = self._submitted_answer_json(snapshot.question_type, answer)
            self.repository.add_attempt(
                session,
                submission_id=submission.id,
                quiz_id=quiz_id,
                question_id=snapshot.question_id,
                idempotency_key=request.idempotency_key,
                submitted_answer_json=submitted_answer_json,
                score=result.score,
                max_score=result.max_score,
                grading_method=result.grading_method,
                feedback_json=feedback_json,
            )

        response = response.model_copy(update={"submission_id": submission.id})
        submission.response_json = response.model_dump()
        MasteryService().apply_submission(session, submission_id=submission.id)
        quiz.status = QUIZ_STATUS_SUBMITTED
        session.commit()
        return response

    def _generate_questions_with_dedup(
        self,
        session: Session,
        *,
        quiz_id: str,
        course_id: str,
        course_name: str,
        settings: QuizGenerateRequest,
        node_versions: list[Any],
        selection_roles: dict[str, str],
        node_versions_by_knowledge_id: dict[str, Any],
        ready_documents: list[Any],
        existing_hashes: set[str],
        prior_stems: list[str],
    ) -> list[PreparedQuestion]:
        adapter = get_llm_adapter()
        prepared_questions: list[PreparedQuestion] = []
        seen_hashes = set(existing_hashes)

        for attempt_number in range(1, 4):
            remaining = settings.question_count - len(prepared_questions)
            if remaining <= 0:
                break
            user_payload = self._build_generation_payload(
                course_name=course_name,
                settings=settings,
                node_versions=node_versions,
                selection_roles=selection_roles,
                ready_documents=ready_documents,
                prior_stems=[*prior_stems, *[item.stem for item in prepared_questions]],
                remaining=remaining,
            )
            try:
                llm_result = adapter.generate_structured_output(
                    prompt_version=QUIZ_GENERATION_PROMPT_VERSION,
                    system_prompt=QUIZ_GENERATION_SYSTEM_PROMPT,
                    user_payload=user_payload,
                    response_model=QuizGenerationCandidate,
                )
            except LLMTemporaryError as exc:
                self.repository.create_generation_run(
                    session,
                    quiz_id=quiz_id,
                    prompt_version=QUIZ_GENERATION_PROMPT_VERSION,
                    model_name="unknown",
                    input_summary_json={"attempt": attempt_number, "requested_count": remaining},
                    output_summary_json={},
                    status="failed",
                    error_code=exc.code,
                )
                self._record_failed_llm_call(
                    session, course_id=course_id, operation="quiz_generation",
                    prompt_version=QUIZ_GENERATION_PROMPT_VERSION, error_code=exc.code,
                    input_summary={"attempt": attempt_number, "requested_count": remaining},
                )
                raise
            except AppError as exc:
                self.repository.create_generation_run(
                    session,
                    quiz_id=quiz_id,
                    prompt_version=QUIZ_GENERATION_PROMPT_VERSION,
                    model_name="unknown",
                    input_summary_json={"attempt": attempt_number, "requested_count": remaining},
                    output_summary_json={},
                    status="failed",
                    error_code=exc.code,
                )
                self._record_failed_llm_call(
                    session, course_id=course_id, operation="quiz_generation",
                    prompt_version=QUIZ_GENERATION_PROMPT_VERSION, error_code=exc.code,
                    input_summary={"attempt": attempt_number, "requested_count": remaining},
                )
                raise

            accepted_this_round = 0
            for candidate in llm_result.data.questions:
                prepared = self._prepare_generated_question(
                    candidate=candidate,
                    node_versions_by_knowledge_id=node_versions_by_knowledge_id,
                    ready_documents=ready_documents,
                )
                if prepared.content_hash in seen_hashes:
                    continue
                prepared_questions.append(prepared)
                seen_hashes.add(prepared.content_hash)
                accepted_this_round += 1
                if len(prepared_questions) >= settings.question_count:
                    break

            self.repository.create_generation_run(
                session,
                quiz_id=quiz_id,
                prompt_version=llm_result.summary.prompt_version,
                model_name=llm_result.summary.model_name,
                input_summary_json={
                    "attempt": attempt_number,
                    "requested_count": remaining,
                    "knowledge_node_count": len(node_versions),
                },
                output_summary_json={
                    "candidate_count": len(llm_result.data.questions),
                    "accepted_count": accepted_this_round,
                },
                status="succeeded",
            )
            self.llm_repository.add_call_log(
                session,
                course_id=course_id,
                operation="quiz_generation",
                provider=llm_result.summary.provider,
                model_name=llm_result.summary.model_name,
                prompt_version=llm_result.summary.prompt_version,
                status="succeeded",
                attempt_count=llm_result.summary.attempt_count,
                duration_ms=llm_result.summary.duration_ms,
                input_summary={"attempt": attempt_number, "requested_count": remaining, "knowledge_node_count": len(node_versions)},
                output_summary={"candidate_count": len(llm_result.data.questions), "accepted_count": accepted_this_round},
            )

        if len(prepared_questions) < settings.question_count:
            raise AppError(
                code="QUIZ_GENERATION_INSUFFICIENT_UNIQUE",
                message="Quiz generation did not produce enough unique questions.",
                status_code=502,
                details={
                    "requested_count": settings.question_count,
                    "generated_count": len(prepared_questions),
                },
            )
        return prepared_questions[: settings.question_count]

    def _record_failed_llm_call(
        self,
        session: Session,
        *,
        course_id: str,
        operation: str,
        prompt_version: str,
        error_code: str,
        input_summary: dict[str, Any],
    ) -> None:
        adapter = get_llm_adapter()
        settings = getattr(adapter, "settings", None)
        self.llm_repository.add_call_log(
            session,
            course_id=course_id,
            operation=operation,
            provider="mock" if getattr(settings, "llm_base_url", "").startswith("mock://") else "openai-compatible",
            model_name=getattr(settings, "llm_model", None) or "unknown",
            prompt_version=prompt_version,
            status="failed",
            error_code=error_code,
            input_summary=input_summary,
        )

    def _build_generation_payload(
        self,
        *,
        course_name: str,
        settings: QuizGenerateRequest,
        node_versions: list[Any],
        selection_roles: dict[str, str],
        ready_documents: list[Any],
        prior_stems: list[str],
        remaining: int,
    ) -> dict[str, Any]:
        knowledge_nodes: list[dict[str, Any]] = []
        remaining_source_chars = QUIZ_SOURCE_CONTEXT_CHAR_LIMIT
        for node in node_versions:
            if not node.content:
                continue
            source_excerpts, used_chars = self._source_excerpts_for_node(
                node,
                remaining_chars=remaining_source_chars,
            )
            remaining_source_chars -= used_chars
            knowledge_nodes.append(
                {
                    "knowledge_node_id": node.knowledge_node_id,
                    "section_label": node.section_label,
                    "title": node.title,
                    "selection_role": selection_roles.get(node.knowledge_node_id, "exploration"),
                    "content": node.content,
                    "source_excerpts": source_excerpts,
                }
            )

        return {
            "course_name": course_name,
            "question_count": remaining,
            "difficulty": settings.difficulty,
            "question_types": settings.question_types,
            "response_schema": {
                "format": "Return a JSON object with one key named questions.",
                "question_fields": [
                    "question_type",
                    "stem",
                    "options",
                    "answer_key_option_ids",
                    "reference_answer",
                    "rubric",
                    "explanation",
                    "difficulty",
                    "knowledge_mappings",
                    "source_chunk_ids",
                    "source_page_numbers",
                ],
                "choice_option_shape": {"id": "A", "text": "option text"},
                "mapping_shape": {
                    "knowledge_node_id": "must exactly match one supplied knowledge_node_id",
                    "relation_role": "primary",
                    "weight": 1.0,
                },
            },
            "generation_rules": [
                "Ask about the meaning, implication, application, contrast, or consequence of the supplied knowledge point content.",
                "Do not ask whether a knowledge point appears in the framework or is grounded in material.",
                "Do not use source metadata, filenames, table-of-contents text, or cover slide text as the tested concept.",
                "Use source_excerpts only as evidence for the supplied knowledge point; do not turn filenames or page labels into questions.",
            ],
            "selection_policy": {
                "review_ratio": REVIEW_QUESTION_RATIO,
                "requested_review_questions": min(
                    math.ceil(remaining * REVIEW_QUESTION_RATIO),
                    sum(role == "review" for role in selection_roles.values()),
                ),
                "requested_exploration_questions": remaining
                - min(
                    math.ceil(remaining * REVIEW_QUESTION_RATIO),
                    sum(role == "review" for role in selection_roles.values()),
                ),
                "review_definition": "Use review targets for concepts with wrong-answer or gap evidence; generate a new variant, not a copy of an old question.",
                "exploration_definition": "Use exploration targets to cover the active leaf framework with lower probability for heavily tested concepts.",
            },
            "knowledge_nodes": knowledge_nodes,
            "prior_question_stems": prior_stems[-20:],
        }

    def _select_generation_nodes(
        self,
        *,
        quiz_id: str,
        settings: QuizGenerateRequest,
        nodes: list[Any],
        selection_stats: dict[str, dict[str, float | int]],
    ) -> tuple[list[Any], dict[str, str]]:
        if not nodes:
            return [], {}
        roles: dict[str, str] = {}
        requested_ids = set(settings.knowledge_node_ids)
        if requested_ids:
            selected = list(nodes)
            for node in selected:
                stats = selection_stats.get(node.knowledge_node_id, {})
                roles[node.knowledge_node_id] = (
                    "review"
                    if int(stats.get("wrong_count", 0)) > 0
                    or float(stats.get("gap_confidence", 0.0)) > 0
                    else "exploration"
                )
            return selected, roles

        rng = random.Random(f"quiz-selection:{quiz_id}")
        context_limit = min(len(nodes), max(settings.question_count * 3, QUIZ_CONTEXT_NODE_LIMIT))
        review_nodes = [
            node
            for node in nodes
            if int(selection_stats.get(node.knowledge_node_id, {}).get("wrong_count", 0)) > 0
            or float(selection_stats.get(node.knowledge_node_id, {}).get("gap_confidence", 0.0)) > 0
        ]
        review_limit = min(
            len(review_nodes),
            max(1, math.ceil(settings.question_count * REVIEW_QUESTION_RATIO) * 2),
        )
        selected_review = self._weighted_sample(
            review_nodes,
            review_limit,
            rng,
            lambda node: self._review_selection_weight(
                selection_stats.get(node.knowledge_node_id, {})
            ),
        )
        selected_ids = {node.knowledge_node_id for node in selected_review}
        for node in selected_review:
            roles[node.knowledge_node_id] = "review"

        exploration_nodes = [node for node in nodes if node.knowledge_node_id not in selected_ids]
        exploration_limit = context_limit - len(selected_review)
        selected_exploration = self._weighted_sample(
            exploration_nodes,
            exploration_limit,
            rng,
            lambda node: self._exploration_selection_weight(
                selection_stats.get(node.knowledge_node_id, {})
            ),
        )
        for node in selected_exploration:
            roles[node.knowledge_node_id] = "exploration"
        return [*selected_review, *selected_exploration], roles

    def _weighted_sample(
        self,
        nodes: list[Any],
        count: int,
        rng: random.Random,
        weight_fn: Any,
    ) -> list[Any]:
        pool = list(nodes)
        selected: list[Any] = []
        for _ in range(min(count, len(pool))):
            weights = [max(0.001, float(weight_fn(node))) for node in pool]
            total = sum(weights)
            threshold = rng.random() * total
            selected_index = 0
            for index, weight in enumerate(weights):
                threshold -= weight
                if threshold <= 0:
                    selected_index = index
                    break
            selected.append(pool.pop(selected_index))
        return selected

    def _review_selection_weight(self, stats: dict[str, float | int]) -> float:
        wrong_count = int(stats.get("wrong_count", 0))
        gap_confidence = float(stats.get("gap_confidence", 0.0))
        mastery = float(stats.get("mastery_estimate", 0.5))
        return 1.0 + 2.0 * wrong_count + 2.0 * gap_confidence + max(0.0, 1.0 - mastery)

    def _exploration_selection_weight(self, stats: dict[str, float | int]) -> float:
        question_count = int(stats.get("question_count", 0))
        return (2.0 if question_count == 0 else 1.0) / math.sqrt(1.0 + question_count)

    def _source_excerpts_for_node(
        self, node_version: Any, *, remaining_chars: int
    ) -> tuple[list[dict[str, Any]], int]:
        excerpts: list[dict[str, Any]] = []
        used_chars = 0
        for source in list(getattr(node_version, "sources", []))[:3]:
            if remaining_chars - used_chars <= 0:
                break
            chunk = getattr(source, "chunk", None)
            text = getattr(chunk, "text", None)
            if not text:
                continue
            normalized_text = " ".join(text.split())
            available = remaining_chars - used_chars
            text_excerpt = normalized_text[:available]
            excerpts.append(
                {
                    "document_id": source.document_id,
                    "filename": source.document.filename,
                    "page_number": source.page_number,
                    "chunk_id": source.chunk_id,
                    "text_excerpt": text_excerpt,
                    "truncated": len(text_excerpt) < len(normalized_text),
                }
            )
            used_chars += len(text_excerpt)
        return excerpts, used_chars

    def _build_fallback_quiz_generation_result(
        self,
        *,
        prompt_version: str,
        settings: QuizGenerateRequest,
        node_versions: list[Any],
        ready_documents: list[Any],
        prior_stems: list[str],
        remaining: int,
    ):
        from app.llm.schemas import LLMRunSummary, LLMStructuredResult

        prior_stem_set = {" ".join(stem.lower().split()) for stem in prior_stems}
        candidates: list[QuizQuestionCandidate] = []
        for index in range(remaining * 3):
            node = node_versions[index % len(node_versions)]
            content = self._node_content(node)
            if not content:
                continue
            question_type = settings.question_types[index % len(settings.question_types)]
            source = self._source_for_node_or_fallback(node, ready_documents, index)
            stem_suffix = index + 1
            if question_type == QUESTION_TYPE_SINGLE_CHOICE:
                stem = f"Which statement best explains {node.title}? #{stem_suffix}"
                candidate = QuizQuestionCandidate(
                    question_type=QUESTION_TYPE_SINGLE_CHOICE,
                    stem=stem,
                    options=[
                        QuestionOptionCandidate(id="A", text=self._fallback_option_text(content)),
                        QuestionOptionCandidate(
                            id="B",
                            text=f"{node.title} is only a slide title and has no conceptual meaning.",
                        ),
                        QuestionOptionCandidate(
                            id="C",
                            text=f"{node.title} means the opposite of the provided explanation.",
                        ),
                    ],
                    answer_key_option_ids=["A"],
                    reference_answer=None,
                    rubric=None,
                    explanation=f"The correct answer matches the knowledge point content for {node.title}.",
                    difficulty=settings.difficulty,
                    knowledge_mappings=[self._fallback_mapping(node)],
                    source_chunk_ids=source["chunk_ids"],
                    source_page_numbers=source["page_numbers"],
                )
            elif question_type == QUESTION_TYPE_MULTIPLE_CHOICE:
                stem = f"Select all statements that correctly describe {node.title}. #{stem_suffix}"
                candidate = QuizQuestionCandidate(
                    question_type=QUESTION_TYPE_MULTIPLE_CHOICE,
                    stem=stem,
                    options=[
                        QuestionOptionCandidate(id="A", text=self._fallback_option_text(content)),
                        QuestionOptionCandidate(
                            id="B",
                            text=f"{node.title} is a teachable concept that can be explained from the source context.",
                        ),
                        QuestionOptionCandidate(
                            id="C",
                            text=f"{node.title} has no associated idea or explanation.",
                        ),
                    ],
                    answer_key_option_ids=["A", "B"],
                    reference_answer=None,
                    rubric=None,
                    explanation=f"The first two statements align with the knowledge point content for {node.title}.",
                    difficulty=settings.difficulty,
                    knowledge_mappings=[self._fallback_mapping(node)],
                    source_chunk_ids=source["chunk_ids"],
                    source_page_numbers=source["page_numbers"],
                )
            else:
                stem = f"Summarize {node.title} in one or two sentences #{stem_suffix}"
                candidate = QuizQuestionCandidate(
                    question_type=QUESTION_TYPE_SHORT_ANSWER,
                    stem=stem,
                    options=[],
                    answer_key_option_ids=[],
                    reference_answer=content,
                    rubric=ShortAnswerRubricCandidate(
                        max_points=2,
                        criteria=[
                            RubricCriterionCandidate(
                                criterion_id="mentions_topic",
                                description="Mentions the target concept.",
                                max_points=1,
                                acceptable_phrases=[node.title.lower()],
                            ),
                            RubricCriterionCandidate(
                                criterion_id="connects_to_material",
                                description="Explains the concept using the provided knowledge point content.",
                                max_points=1,
                                acceptable_phrases=[
                                    phrase.lower()
                                    for phrase in self._key_phrases(content)
                                ],
                            ),
                        ],
                    ),
                    explanation=f"A complete answer should explain {node.title}: {content}",
                    difficulty=settings.difficulty,
                    knowledge_mappings=[self._fallback_mapping(node)],
                    source_chunk_ids=source["chunk_ids"],
                    source_page_numbers=source["page_numbers"],
                )

            normalized_stem = " ".join(candidate.stem.lower().split())
            if normalized_stem in prior_stem_set:
                continue
            candidates.append(candidate)
            prior_stem_set.add(normalized_stem)
            if len(candidates) >= remaining:
                break

        return LLMStructuredResult(
            summary=LLMRunSummary(
                model_name="deterministic-fallback",
                prompt_version=prompt_version,
                provider="backend",
            ),
            data=QuizGenerationCandidate(questions=candidates),
        )

    def _fallback_mapping(self, node_version: Any) -> QuestionKnowledgeMappingCandidate:
        return QuestionKnowledgeMappingCandidate(
            knowledge_node_id=node_version.knowledge_node_id,
            relation_role="primary",
            weight=1.0,
        )

    def _node_content(self, node_version: Any) -> str:
        return " ".join((getattr(node_version, "content", None) or "").split())

    def _fallback_option_text(self, content: str) -> str:
        if len(content) <= 500:
            return content
        return f"{content[:497].rstrip()}..."

    def _key_phrases(self, content: str) -> list[str]:
        words = [
            word.strip(".,;:()[]{}").lower()
            for word in content.split()
            if len(word.strip(".,;:()[]{}")) >= 5
        ]
        unique_words = list(dict.fromkeys(words))
        return unique_words[:6] or [content.lower()[:40]]

    def _source_for_node_or_fallback(
        self, node_version: Any, ready_documents: list[Any], index: int
    ) -> dict[str, list[Any]]:
        sources = list(getattr(node_version, "sources", []))
        chunk_ids = [source.chunk_id for source in sources if source.chunk_id]
        page_numbers = [source.page_number for source in sources if source.page_number >= 1]
        if chunk_ids or page_numbers:
            return {"chunk_ids": chunk_ids[:3], "page_numbers": sorted(set(page_numbers))[:3]}
        return self._source_for_fallback_question(ready_documents, index)

    def _source_for_fallback_question(self, ready_documents: list[Any], index: int) -> dict[str, list[Any]]:
        chunks = [chunk for document in ready_documents for chunk in document.chunks]
        if chunks:
            chunk = chunks[index % len(chunks)]
            return {"chunk_ids": [chunk.id], "page_numbers": [chunk.page_start]}
        pages = [
            page
            for document in ready_documents
            for page in document.pages
            if page.extraction_status == "extracted"
        ]
        if pages:
            page = pages[index % len(pages)]
            return {"chunk_ids": [], "page_numbers": [page.page_number]}
        return {"chunk_ids": [], "page_numbers": []}

    def _is_llm_parse_error(self, exc: AppError) -> bool:
        return (
            exc.code == "LLM_OUTPUT_INVALID"
            and exc.message == "LLM returned invalid structured output."
        )

    def _prepare_generated_question(
        self,
        *,
        candidate: QuizQuestionCandidate,
        node_versions_by_knowledge_id: dict[str, Any],
        ready_documents: list[Any],
    ) -> PreparedQuestion:
        question_type = candidate.question_type
        if question_type not in {
            QUESTION_TYPE_SINGLE_CHOICE,
            QUESTION_TYPE_MULTIPLE_CHOICE,
            QUESTION_TYPE_SHORT_ANSWER,
        }:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Generated question type is not supported.",
                status_code=502,
            )

        option_ids: list[str] = []
        options_json: list[dict] | None = None
        answer_key_json: dict[str, Any] | None = None
        rubric_json: dict[str, Any] | None = None
        max_score = 1.0

        if question_type in {QUESTION_TYPE_SINGLE_CHOICE, QUESTION_TYPE_MULTIPLE_CHOICE}:
            if not candidate.options:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Choice questions must include options.",
                    status_code=502,
                )
            options = [QuizQuestionOption(id=option.id, text=option.text) for option in candidate.options]
            option_ids = [option.id for option in options]
            if len(set(option_ids)) != len(option_ids):
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Choice question option identifiers must be unique.",
                    status_code=502,
                )
            answer_ids = list(dict.fromkeys(candidate.answer_key_option_ids))
            if not answer_ids:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Choice questions must include at least one answer key option.",
                    status_code=502,
                )
            if not set(answer_ids).issubset(set(option_ids)):
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Choice question answer keys must reference valid options.",
                    status_code=502,
                )
            if question_type == QUESTION_TYPE_SINGLE_CHOICE and len(answer_ids) != 1:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Single-choice questions must have exactly one correct option.",
                    status_code=502,
                )
            if question_type == QUESTION_TYPE_MULTIPLE_CHOICE and len(answer_ids) < 2:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Multiple-choice questions must have at least two correct options.",
                    status_code=502,
                )
            options_json = [option.model_dump() for option in options]
            answer_key_json = {"option_ids": answer_ids}
        else:
            if candidate.rubric is None or candidate.reference_answer is None:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Short-answer questions must include a rubric and reference answer.",
                    status_code=502,
                )
            rubric = QuestionRubric.model_validate(candidate.rubric.model_dump())
            max_score = float(rubric.max_points)
            rubric_json = rubric.model_dump()
            answer_key_json = {"reference_answer": candidate.reference_answer}

        mappings: list[QuestionKnowledgeMappingSnapshot] = []
        for mapping in candidate.knowledge_mappings:
            node_version = node_versions_by_knowledge_id.get(mapping.knowledge_node_id)
            if node_version is None:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Generated question references an unknown knowledge node.",
                    status_code=502,
                    details={"knowledge_node_id": mapping.knowledge_node_id},
                )
            mappings.append(
                QuestionKnowledgeMappingSnapshot(
                    knowledge_node_id=node_version.knowledge_node_id,
                    node_version_id=node_version.id,
                    title=node_version.title,
                    relation_role=mapping.relation_role,
                    weight=float(mapping.weight),
                )
            )

        self._validate_question_quality(candidate)
        chunk_ids = {chunk.id for document in ready_documents for chunk in document.chunks}
        valid_chunk_ids = [chunk_id for chunk_id in candidate.source_chunk_ids if chunk_id in chunk_ids]
        page_numbers = sorted({page for page in candidate.source_page_numbers if page >= 1})
        content_hash = self._normalize_stem_hash(candidate.stem)
        snapshot = QuizQuestionSnapshot(
            question_id="pending",
            question_type=question_type,
            stem=candidate.stem.strip(),
            options=[QuizQuestionOption.model_validate(option) for option in (options_json or [])],
            answer_key_option_ids=list(answer_key_json.get("option_ids", [])) if answer_key_json else [],
            reference_answer=answer_key_json.get("reference_answer") if answer_key_json else None,
            rubric=QuestionRubric.model_validate(rubric_json) if rubric_json else None,
            explanation=candidate.explanation,
            difficulty=candidate.difficulty,
            max_score=max_score,
            knowledge_mappings=mappings,
            source_metadata={"chunk_ids": valid_chunk_ids, "page_numbers": page_numbers},
        )
        return PreparedQuestion(
            question_type=question_type,
            stem=snapshot.stem,
            options_json=options_json,
            answer_key_json=answer_key_json,
            rubric_json=rubric_json,
            explanation=candidate.explanation,
            difficulty=candidate.difficulty,
            source_metadata_json=snapshot.source_metadata,
            content_hash=content_hash,
            snapshot=snapshot,
        )

    def _validate_question_quality(self, candidate: QuizQuestionCandidate) -> None:
        forbidden_phrases = [
            "appears in the course framework",
            "appears in the framework",
            "grounded in uploaded material",
            "grounded in the uploaded material",
            "supported by the course material",
            "supported by the material",
            "is covered by the course",
            "not covered by the course",
            "choose the best supported statement",
            "select all statements supported by the material",
            "table of contents",
            "acknowledgement",
            "acknowledgment",
        ]
        text_parts = [candidate.stem, candidate.explanation or "", candidate.reference_answer or ""]
        text_parts.extend(option.text for option in candidate.options)
        combined = " ".join(text_parts).lower()
        if any(phrase in combined for phrase in forbidden_phrases):
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Generated question tests source/framework metadata instead of knowledge content.",
                status_code=502,
            )

    def _grade_answer(
        self,
        snapshot: QuizQuestionSnapshot,
        answer: QuizAnswerInput,
    ) -> tuple[QuizQuestionResultResponse, dict]:
        if snapshot.question_type in {QUESTION_TYPE_SINGLE_CHOICE, QUESTION_TYPE_MULTIPLE_CHOICE}:
            selected_option_ids = list(answer.selected_option_ids or [])
            self._validate_selected_option_ids(snapshot, selected_option_ids)
            expected = set(snapshot.answer_key_option_ids)
            selected = set(selected_option_ids)
            score = snapshot.max_score if selected == expected else 0.0
            feedback_json = {
                "correct": selected == expected,
                "feedback_text": snapshot.explanation,
            }
            return (
                QuizQuestionResultResponse(
                    question_id=snapshot.question_id,
                    score=float(score),
                    max_score=snapshot.max_score,
                    grading_method="deterministic",
                    correct=selected == expected,
                    feedback_text=snapshot.explanation,
                ),
                feedback_json,
            )

        if answer.text is None:
            raise AppError(
                code="VALIDATION_ERROR",
                message="Short-answer questions require a text response.",
                status_code=422,
            )
        if snapshot.rubric is None or snapshot.reference_answer is None:
            raise AppError(
                code="INTERNAL_SERVER_ERROR",
                message="Short-answer snapshot is missing rubric data.",
                status_code=500,
            )

        adapter = get_llm_adapter()
        adapter.ensure_available()
        try:
            llm_result = adapter.generate_structured_output(
                prompt_version=SHORT_ANSWER_GRADING_PROMPT_VERSION,
                system_prompt=SHORT_ANSWER_GRADING_SYSTEM_PROMPT,
                user_payload={
                    "question": snapshot.stem,
                    "reference_answer": snapshot.reference_answer,
                    "rubric": snapshot.rubric.model_dump(),
                    "student_answer": answer.text,
                },
                response_model=ShortAnswerGradingCandidate,
            )
        except LLMTemporaryError as exc:
            raise AppError(
                code=exc.code,
                message="Short-answer grading is temporarily unavailable.",
                status_code=503,
            ) from exc

        rubric_criteria = {criterion.criterion_id: criterion for criterion in snapshot.rubric.criteria}
        awarded_total = 0.0
        criterion_scores: list[dict[str, Any]] = []
        for criterion_score in llm_result.data.criterion_scores:
            criterion = rubric_criteria.get(criterion_score.criterion_id)
            if criterion is None:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Short-answer grading referenced an unknown rubric criterion.",
                    status_code=502,
                )
            if criterion_score.awarded_points > criterion.max_points:
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message="Short-answer grading exceeded the rubric criterion max points.",
                    status_code=502,
                )
            awarded_total += float(criterion_score.awarded_points)
            criterion_scores.append(criterion_score.model_dump())
        if awarded_total > snapshot.max_score + 1e-6:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Short-answer grading exceeded the question max score.",
                status_code=502,
            )
        if abs(awarded_total - llm_result.data.score) > 1e-6:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message="Short-answer grading score did not match the rubric breakdown.",
                status_code=502,
            )

        feedback_json = {
            "feedback_text": llm_result.data.feedback,
            "rationale": llm_result.data.rationale,
            "criterion_scores": criterion_scores,
            "model_name": llm_result.summary.model_name,
            "prompt_version": llm_result.summary.prompt_version,
        }
        return (
            QuizQuestionResultResponse(
                question_id=snapshot.question_id,
                score=float(llm_result.data.score),
                max_score=snapshot.max_score,
                grading_method="rubric_llm",
                correct=None,
                feedback_text=llm_result.data.feedback,
            ),
            feedback_json,
        )

    def _validate_selected_option_ids(
        self,
        snapshot: QuizQuestionSnapshot,
        selected_option_ids: list[str],
    ) -> None:
        if snapshot.question_type == QUESTION_TYPE_SHORT_ANSWER:
            raise AppError(
                code="VALIDATION_ERROR",
                message="Short-answer questions do not accept option identifiers.",
                status_code=422,
            )
        option_ids = [option.id for option in snapshot.options]
        if len(set(selected_option_ids)) != len(selected_option_ids):
            raise AppError(
                code="INVALID_OPTION_IDENTIFIER",
                message="Duplicate option identifiers are not allowed.",
                status_code=400,
            )
        invalid_ids = [option_id for option_id in selected_option_ids if option_id not in option_ids]
        if invalid_ids:
            raise AppError(
                code="INVALID_OPTION_IDENTIFIER",
                message="Submitted option identifiers must belong to the quiz question.",
                status_code=400,
                details={"invalid_option_ids": invalid_ids},
            )
        if snapshot.question_type == QUESTION_TYPE_SINGLE_CHOICE and len(selected_option_ids) > 1:
            raise AppError(
                code="INVALID_OPTION_IDENTIFIER",
                message="Single-choice questions accept at most one option identifier.",
                status_code=400,
            )

    def _validate_submission_shape(
        self,
        quiz: Any,
        answers: list[QuizAnswerInput],
    ) -> dict[str, QuizAnswerInput]:
        answers_by_question_id: dict[str, QuizAnswerInput] = {}
        for answer in answers:
            if answer.question_id in answers_by_question_id:
                raise AppError(
                    code="VALIDATION_ERROR",
                    message="Each quiz question can be submitted only once per request.",
                    status_code=422,
                    details={"question_id": answer.question_id},
                )
            answers_by_question_id[answer.question_id] = answer

        expected_question_ids = {
            QuizQuestionSnapshot.model_validate(quiz_question.question_snapshot_json).question_id
            for quiz_question in quiz.quiz_questions
        }
        submitted_question_ids = set(answers_by_question_id)
        missing = sorted(expected_question_ids - submitted_question_ids)
        extra = sorted(submitted_question_ids - expected_question_ids)
        if missing or extra:
            raise AppError(
                code="VALIDATION_ERROR",
                message="Quiz submission must include exactly one answer for each quiz question.",
                status_code=422,
                details={"missing_question_ids": missing, "extra_question_ids": extra},
            )
        return answers_by_question_id

    def _validate_requested_scope(self, node_versions: list[Any], knowledge_node_ids: list[str]) -> None:
        if not knowledge_node_ids:
            return
        known_ids = {node.knowledge_node_id for node in node_versions}
        missing = sorted(set(knowledge_node_ids) - known_ids)
        if missing:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Some requested knowledge nodes are not present in the active framework.",
                status_code=404,
                details={"knowledge_node_ids": missing},
            )

    def _to_public_question_response(self, ordinal: int, snapshot_json: dict) -> QuizQuestionResponse:
        snapshot = QuizQuestionSnapshot.model_validate(snapshot_json)
        return QuizQuestionResponse(
            question_id=snapshot.question_id,
            ordinal=ordinal,
            question_type=snapshot.question_type,
            stem=snapshot.stem,
            options=snapshot.options,
            difficulty=snapshot.difficulty,
            max_score=snapshot.max_score,
        )

    def _submitted_answer_json(
        self, question_type: str, answer: QuizAnswerInput
    ) -> dict[str, Any]:
        if question_type == QUESTION_TYPE_SHORT_ANSWER:
            return {"text": answer.text}
        return {"selected_option_ids": list(answer.selected_option_ids or [])}

    def _normalize_stem_hash(self, stem: str) -> str:
        normalized = " ".join(stem.lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
