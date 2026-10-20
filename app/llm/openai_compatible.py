from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import AppError
from app.llm.base import LLMAdapter, LLMTemporaryError
from app.llm.schemas import (
    KnowledgeFrameworkCandidate,
    KnowledgeNodeCandidate,
    KnowledgeRelationCandidate,
    KnowledgeSourceCandidate,
    LLMRunSummary,
    LLMStructuredResult,
    QuestionKnowledgeMappingCandidate,
    QuestionOptionCandidate,
    QuizGenerationCandidate,
    QuizQuestionCandidate,
    RubricCriterionCandidate,
    ShortAnswerGradingCandidate,
    ShortAnswerRubricCandidate,
)


class OpenAICompatibleAdapter(LLMAdapter):
    def __init__(self) -> None:
        self.settings = get_settings()

    def ensure_available(self) -> None:
        if self.settings.llm_base_url and self.settings.llm_base_url.startswith("mock://"):
            return
        if not self.settings.llm_base_url or not self.settings.llm_model:
            raise AppError(
                code="LLM_NOT_CONFIGURED",
                message="LLM base URL and model must be configured for LLM-backed features.",
                status_code=400,
            )
        if not self.settings.llm_api_key:
            raise AppError(
                code="LLM_NOT_CONFIGURED",
                message="LLM API key must be configured through environment variables.",
                status_code=400,
            )

    def generate_structured_output(
        self,
        *,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> LLMStructuredResult:
        self.ensure_available()
        if self.settings.llm_base_url and self.settings.llm_base_url.startswith("mock://"):
            return self._generate_mock_output(
                prompt_version=prompt_version,
                user_payload=user_payload,
                response_model=response_model,
            )
        return self._generate_http_output(
            prompt_version=prompt_version,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_model=response_model,
        )

    def _generate_http_output(
        self,
        *,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> LLMStructuredResult:
        assert self.settings.llm_base_url is not None
        assert self.settings.llm_model is not None
        assert self.settings.llm_api_key is not None

        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        invalid_type = "unknown"
        started = time.perf_counter()
        validation_hint = ""
        for attempt in range(self.settings.llm_max_retries + 1):
            retry_instruction = ""
            if attempt:
                retry_instruction = (
                    "\n\nThis is a structured-output retry. The previous response was invalid. "
                    "Return exactly one valid JSON object, with no Markdown fences, commentary, "
                    "or extra fields. Follow every field type, required field, enum, and source "
                    "reference constraint in the requested schema."
                )
                retry_instruction += validation_hint
            request_body = {
                "model": self.settings.llm_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt + retry_instruction},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
            }
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(
                        f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                        json=request_body,
                        headers=headers,
                    )
            except httpx.TimeoutException as exc:
                raise LLMTemporaryError(code="LLM_TIMEOUT", message="LLM request timed out.") from exc
            except httpx.HTTPError as exc:
                raise LLMTemporaryError(code="LLM_NETWORK_ERROR", message="LLM request failed.") from exc

            if response.status_code in {408, 429, 500, 502, 503, 504}:
                raise LLMTemporaryError(
                    code="LLM_UPSTREAM_TEMPORARY",
                    message=f"Temporary LLM error: HTTP {response.status_code}.",
                )
            if response.status_code in {401, 403}:
                raise AppError(
                    code="LLM_AUTH_FAILED",
                    message="LLM authentication failed.",
                    status_code=400,
                )
            if response.status_code >= 400:
                raise AppError(
                    code="LLM_REQUEST_FAILED",
                    message=f"LLM request failed with HTTP {response.status_code}.",
                    status_code=502,
                )

            try:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("LLM content must be a JSON string.")
                parsed_payload = json.loads(self._extract_json_content(content))
                normalized_payload = self._normalize_structured_payload(
                    parsed_payload,
                    response_model=response_model,
                    user_payload=user_payload,
                )
                data = response_model.model_validate(normalized_payload)
            except (KeyError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                invalid_type = type(exc).__name__
                if attempt < self.settings.llm_max_retries:
                    if isinstance(exc, ValidationError):
                        validation_hint = self._validation_retry_instruction(exc)
                    continue
                raise AppError(
                    code="LLM_OUTPUT_INVALID",
                    message=f"LLM returned invalid structured output ({invalid_type}) after {attempt + 1} attempt(s).",
                    status_code=502,
                ) from exc

            return LLMStructuredResult(
                summary=LLMRunSummary(
                    model_name=self.settings.llm_model,
                    prompt_version=prompt_version,
                    provider="openai-compatible",
                    attempt_count=attempt + 1,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                ),
                data=data,
            )

        raise AppError(
            code="LLM_OUTPUT_INVALID",
            message=f"LLM returned invalid structured output ({invalid_type}).",
            status_code=502,
        )

    def _normalize_structured_payload(
        self,
        payload: Any,
        *,
        response_model: type[BaseModel],
        user_payload: dict[str, Any],
    ) -> Any:
        """Normalize safe presentation variants without inventing grading facts."""
        if response_model is QuizGenerationCandidate:
            return self._normalize_quiz_payload(payload)
        if response_model is KnowledgeFrameworkCandidate:
            return self._normalize_knowledge_payload(payload, user_payload=user_payload)
        return payload

    def _normalize_quiz_payload(self, payload: Any) -> Any:
        if isinstance(payload, list):
            payload = {"questions": payload}
        if not isinstance(payload, dict):
            return payload
        normalized = deepcopy(payload)
        if "questions" not in normalized:
            if "question" in normalized and isinstance(normalized["question"], dict):
                normalized["questions"] = [normalized.pop("question")]
            elif "items" in normalized and isinstance(normalized["items"], list):
                normalized["questions"] = normalized.pop("items")

        questions = normalized.get("questions")
        if not isinstance(questions, list):
            return normalized
        normalized_questions = []
        for raw_question in questions:
            if not isinstance(raw_question, dict):
                normalized_questions.append(raw_question)
                continue
            question = dict(raw_question)
            self._rename_if_missing(question, "question_type", "type")
            self._rename_if_missing(question, "stem", "question")
            self._rename_if_missing(question, "options", "choices")
            self._rename_if_missing(question, "answer_key_option_ids", "correct_option_ids")
            self._rename_if_missing(question, "answer_key_option_ids", "answer")
            self._rename_if_missing(question, "knowledge_mappings", "knowledge_points")
            self._rename_if_missing(question, "reference_answer", "expected_answer")
            question_type = question.get("question_type")
            question["question_type"] = {
                "single": "single_choice",
                "multiple": "multiple_choice",
                "short": "short_answer",
            }.get(question_type, question_type)
            options = question.get("options")
            if isinstance(options, dict):
                question["options"] = [
                    {"id": str(option_id), "text": str(option_text)}
                    for option_id, option_text in options.items()
                ]
            elif isinstance(options, list) and all(isinstance(option, str) for option in options):
                question["options"] = [
                    {"id": chr(ord("A") + index), "text": option}
                    for index, option in enumerate(options)
                ]
            for field in ("answer_key_option_ids", "source_chunk_ids", "source_page_numbers"):
                if isinstance(question.get(field), str):
                    question[field] = [question[field]]
            if isinstance(question.get("knowledge_mappings"), dict):
                question["knowledge_mappings"] = [question["knowledge_mappings"]]
            normalized_questions.append(question)
        normalized["questions"] = normalized_questions
        return normalized

    def _normalize_knowledge_payload(self, payload: Any, *, user_payload: dict[str, Any]) -> Any:
        if not isinstance(payload, dict):
            return payload
        normalized = deepcopy(payload)
        if "nodes" not in normalized:
            for alias in ("knowledge_points", "topics", "items"):
                if isinstance(normalized.get(alias), list):
                    normalized["nodes"] = normalized.pop(alias)
                    break
        normalized.setdefault("root_title", user_payload.get("course_name", "Knowledge Framework"))
        normalized.setdefault("relations", [])
        self._normalize_knowledge_nodes(normalized.get("nodes"))
        return normalized

    def _normalize_knowledge_nodes(self, nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for raw_node in nodes:
            if not isinstance(raw_node, dict):
                continue
            self._rename_if_missing(raw_node, "content", "description")
            self._rename_if_missing(raw_node, "content", "explanation")
            self._rename_if_missing(raw_node, "children", "subtopics")
            if isinstance(raw_node.get("source"), dict):
                raw_node["sources"] = [raw_node.pop("source")]
            self._normalize_knowledge_nodes(raw_node.get("children"))

    def _rename_if_missing(self, data: dict[str, Any], target: str, source: str) -> None:
        if target not in data and source in data:
            data[target] = data.pop(source)

    def _validation_retry_instruction(self, exc: ValidationError) -> str:
        locations = []
        for error in exc.errors()[:8]:
            location = ".".join(str(item) for item in error.get("loc", [])) or "root"
            locations.append(f"{location}: {error.get('type', 'invalid')}")
        return (
            "\n\nPrevious response failed schema validation at these fields: "
            + "; ".join(locations)
            + ". Correct those fields and return only the requested JSON object."
        )

    def _extract_json_content(self, content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM content does not contain a JSON object.")
        return stripped[start : end + 1]

    def _generate_mock_output(
        self,
        *,
        prompt_version: str,
        user_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> LLMStructuredResult:
        candidate = self._build_mock_candidate(user_payload, response_model=response_model)
        data = response_model.model_validate(candidate)
        return LLMStructuredResult(
            summary=LLMRunSummary(
                model_name=self.settings.llm_model or "mock-llm",
                prompt_version=prompt_version,
                provider="mock",
                attempt_count=1,
                duration_ms=0,
            ),
            data=data,
        )

    def _build_mock_candidate(
        self, user_payload: dict[str, Any], *, response_model: type[BaseModel]
    ) -> dict[str, Any]:
        if response_model is KnowledgeFrameworkCandidate:
            return self._build_mock_knowledge_framework_candidate(user_payload)
        if response_model is QuizGenerationCandidate:
            return self._build_mock_quiz_generation_candidate(user_payload)
        if response_model is ShortAnswerGradingCandidate:
            return self._build_mock_short_answer_grading_candidate(user_payload)
        raise AppError(
            code="LLM_OUTPUT_INVALID",
            message="The mock LLM adapter does not support this response model.",
            status_code=500,
        )

    def _build_mock_knowledge_framework_candidate(self, user_payload: dict[str, Any]) -> dict[str, Any]:
        documents = user_payload.get("documents", [])
        root_title = user_payload.get("course_name", "Knowledge Framework")
        root_description = "Generated by the built-in mock LLM adapter."
        nodes: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        leaf_refs: list[str] = []

        for document_index, document in enumerate(documents, start=1):
            child_nodes: list[dict[str, Any]] = []
            content = document.get("content", "")
            for chunk_index, segment in enumerate(document.get("source_segments", [])[:6], start=1):
                segment_text = content[
                    segment.get("start_char", 0) : segment.get("end_char", len(content))
                ]
                title = self._mock_title(segment_text, fallback=f"Topic {chunk_index}")
                ref = f"doc{document_index}_chunk{chunk_index}"
                leaf_refs.append(ref)
                child_nodes.append(
                    KnowledgeNodeCandidate(
                        ref=ref,
                        title=title,
                        content=self._mock_content(segment_text),
                        sources=[
                            KnowledgeSourceCandidate(
                                document_id=document["document_id"],
                                page_number=segment["page_start"],
                                chunk_id=segment["chunk_id"],
                                evidence_type="chunk",
                            )
                        ],
                        children=[],
                    ).model_dump()
                )

            if not child_nodes:
                for page in document.get("pages", [])[:3]:
                    if page.get("extraction_status") != "extracted":
                        continue
                    ref = f"doc{document_index}_page{page['page_number']}"
                    leaf_refs.append(ref)
                    child_nodes.append(
                        KnowledgeNodeCandidate(
                            ref=ref,
                            title=self._mock_title(
                                page.get("text_preview") or "",
                                fallback=f"Page {page['page_number']}",
                            ),
                            content=page.get("text_preview"),
                            sources=[
                                KnowledgeSourceCandidate(
                                    document_id=document["document_id"],
                                    page_number=page["page_number"],
                                    evidence_type="page_excerpt",
                                )
                            ],
                            children=[],
                        ).model_dump()
                    )

            document_node = KnowledgeNodeCandidate(
                ref=f"doc{document_index}",
                title=document.get("filename", f"Document {document_index}"),
                content=f"Knowledge extracted from {document.get('filename', 'document')}.",
                sources=[],
                children=child_nodes,
            )
            nodes.append(document_node.model_dump())

        for left, right in zip(leaf_refs, leaf_refs[1:]):
            relations.append(
                KnowledgeRelationCandidate(
                    source_ref=left,
                    target_ref=right,
                    relation_type="related",
                    confidence=0.5,
                    evidence="Documents mention these topics in nearby context.",
                ).model_dump()
            )

        return KnowledgeFrameworkCandidate(
            root_title=root_title,
            root_description=root_description,
            nodes=nodes,
            relations=relations,
        ).model_dump()

    def _mock_title(self, text: str, *, fallback: str) -> str:
        normalized = " ".join(text.replace("\n", " ").split())
        if not normalized:
            return fallback
        return normalized[:80]

    def _mock_content(self, text: str) -> str | None:
        normalized = " ".join(text.replace("\n", " ").split())
        if not normalized:
            return None
        return normalized[:200]

    def _build_mock_quiz_generation_candidate(self, user_payload: dict[str, Any]) -> dict[str, Any]:
        knowledge_nodes = user_payload.get("knowledge_nodes", [])
        question_count = int(user_payload.get("question_count", 1))
        question_types = user_payload.get("question_types", ["single_choice"])
        prior_question_stems = set(user_payload.get("prior_question_stems", []))

        questions: list[dict[str, Any]] = []
        offset = len(prior_question_stems)
        for index in range(question_count):
            question_type = question_types[index % len(question_types)]
            knowledge_node = knowledge_nodes[index % max(len(knowledge_nodes), 1)]
            title = knowledge_node.get("title") or f"Topic {index + 1}"
            content = knowledge_node.get("content") or f"{title} is a course concept."
            source_excerpts = knowledge_node.get("source_excerpts", [])
            chunk_ids = [
                source["chunk_id"]
                for source in source_excerpts[:2]
                if source.get("chunk_id")
            ]
            page_numbers = [
                source["page_number"]
                for source in source_excerpts[:2]
                if "page_number" in source
            ]
            stem_suffix = offset + index + 1
            if question_type == "single_choice":
                question = QuizQuestionCandidate(
                    question_type=question_type,
                    stem=f"Which statement best explains {title}? #{stem_suffix}",
                    options=[
                        QuestionOptionCandidate(id="A", text=str(content)[:500]),
                        QuestionOptionCandidate(id="B", text=f"{title} is only a label without conceptual meaning."),
                        QuestionOptionCandidate(id="C", text=f"{title} means the opposite of the provided explanation."),
                    ],
                    answer_key_option_ids=["A"],
                    explanation=f"The correct answer matches the knowledge point content for {title}.",
                    difficulty=user_payload.get("difficulty", "low"),
                    knowledge_mappings=[
                        QuestionKnowledgeMappingCandidate(
                            knowledge_node_id=knowledge_node.get("knowledge_node_id", "unknown"),
                            relation_role="primary",
                            weight=1.0,
                        )
                    ],
                    source_chunk_ids=chunk_ids[:2],
                    source_page_numbers=page_numbers[:2],
                )
            elif question_type == "multiple_choice":
                question = QuizQuestionCandidate(
                    question_type=question_type,
                    stem=f"Select all statements that correctly describe {title}. #{stem_suffix}",
                    options=[
                        QuestionOptionCandidate(id="A", text=str(content)[:500]),
                        QuestionOptionCandidate(id="B", text=f"{title} is a teachable idea with a concrete explanation."),
                        QuestionOptionCandidate(id="C", text=f"{title} has no associated idea or explanation."),
                    ],
                    answer_key_option_ids=["A", "B"],
                    explanation=f"The first two options align with the knowledge point content for {title}.",
                    difficulty=user_payload.get("difficulty", "low"),
                    knowledge_mappings=[
                        QuestionKnowledgeMappingCandidate(
                            knowledge_node_id=knowledge_node.get("knowledge_node_id", "unknown"),
                            relation_role="primary",
                            weight=1.0,
                        )
                    ],
                    source_chunk_ids=chunk_ids[:2],
                    source_page_numbers=page_numbers[:2],
                )
            else:
                normalized_title = title.lower()
                question = QuizQuestionCandidate(
                    question_type="short_answer",
                    stem=f"Summarize {title} in one or two sentences #{stem_suffix}",
                    reference_answer=str(content)[:500],
                    rubric=ShortAnswerRubricCandidate(
                        max_points=2,
                        criteria=[
                            RubricCriterionCandidate(
                                criterion_id="mentions_topic",
                                description="Mentions the named concept.",
                                max_points=1,
                                acceptable_phrases=[normalized_title],
                            ),
                            RubricCriterionCandidate(
                                criterion_id="mentions_material_support",
                                description="Explains the concept using the expected knowledge point content.",
                                max_points=1,
                                acceptable_phrases=[
                                    word.strip(".,;:()[]{}").lower()
                                    for word in str(content).split()[:8]
                                    if len(word.strip(".,;:()[]{}")) >= 5
                                ],
                            ),
                        ],
                    ),
                    explanation=f"The answer should explain {title}: {str(content)[:300]}",
                    difficulty=user_payload.get("difficulty", "low"),
                    knowledge_mappings=[
                        QuestionKnowledgeMappingCandidate(
                            knowledge_node_id=knowledge_node.get("knowledge_node_id", "unknown"),
                            relation_role="primary",
                            weight=1.0,
                        )
                    ],
                    source_chunk_ids=chunk_ids[:2],
                    source_page_numbers=page_numbers[:2],
                )
            if question.stem in prior_question_stems:
                continue
            questions.append(question.model_dump())

        return QuizGenerationCandidate(questions=questions).model_dump()

    def _build_mock_short_answer_grading_candidate(self, user_payload: dict[str, Any]) -> dict[str, Any]:
        student_answer = str(user_payload.get("student_answer", "")).lower()
        rubric = user_payload.get("rubric", {})
        criteria = rubric.get("criteria", [])
        criterion_scores: list[dict[str, Any]] = []
        total_score = 0.0
        for criterion in criteria:
            acceptable_phrases = [phrase.lower() for phrase in criterion.get("acceptable_phrases", [])]
            matched = any(phrase and phrase in student_answer for phrase in acceptable_phrases)
            awarded_points = float(criterion.get("max_points", 0)) if matched else 0.0
            total_score += awarded_points
            criterion_scores.append(
                {
                    "criterion_id": criterion["criterion_id"],
                    "awarded_points": awarded_points,
                    "rationale": "Matched expected phrases." if matched else "Did not match expected phrases.",
                }
            )

        if total_score == 0 and student_answer.strip():
            total_score = 0.0
        feedback = "Rubric points awarded based on the matched key ideas."
        rationale = "The mock grader checks whether the answer contains rubric phrases."
        return ShortAnswerGradingCandidate(
            score=total_score,
            criterion_scores=criterion_scores,
            feedback=feedback,
            rationale=rationale,
        ).model_dump()


def get_llm_adapter() -> LLMAdapter:
    return OpenAICompatibleAdapter()
