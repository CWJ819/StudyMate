from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.schemas.material import DocumentParsePayload
from app.services.knowledge_service import KnowledgeBuildPayloadModel, KnowledgeService
from app.services.material_service import MaterialService
from app.services.quiz_service import QuizGeneratePayloadModel, QuizService


@dataclass(frozen=True)
class JobHandlerSpec:
    payload_model: type[BaseModel]
    handler: Callable[[Session, BaseModel], None]


def _handle_document_parse(session: Session, payload: DocumentParsePayload) -> None:
    MaterialService().process_document_parse_job(session, document_id=payload.document_id)


def _handle_knowledge_build(session: Session, payload: KnowledgeBuildPayloadModel) -> None:
    KnowledgeService().build_framework_job(
        session,
        course_id=payload.course_id,
        framework_version_id=payload.framework_version_id,
        reference_outline=payload.reference_outline,
    )


def _handle_quiz_generation(session: Session, payload: QuizGeneratePayloadModel) -> None:
    QuizService().generate_quiz_job(
        session,
        course_id=payload.course_id,
        quiz_id=payload.quiz_id,
    )


HANDLERS: dict[str, JobHandlerSpec] = {
    "document.parse": JobHandlerSpec(
        payload_model=DocumentParsePayload,
        handler=_handle_document_parse,
    ),
    "knowledge_framework.build": JobHandlerSpec(
        payload_model=KnowledgeBuildPayloadModel,
        handler=_handle_knowledge_build,
    ),
    "quiz.generate": JobHandlerSpec(
        payload_model=QuizGeneratePayloadModel,
        handler=_handle_quiz_generation,
    ),
}


def get_handler_spec(job_type: str) -> JobHandlerSpec:
    return HANDLERS[job_type]
