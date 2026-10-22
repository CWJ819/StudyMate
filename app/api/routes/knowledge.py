import threading
from typing import Literal

from fastapi import APIRouter, Query

from app.db.session import session_scope
from app.jobs.runner import get_job_runner
from app.schemas.knowledge import (
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeFrameworkResponse,
    KnowledgeGraphResponse,
    KnowledgeHighlightsResponse,
    KnowledgeNodeDetailResponse,
    KnowledgeScoredTreeResponse,
    KnowledgeVersionResponse,
)
from app.services.knowledge_scoring import HIGHLIGHT_LIMIT_DEFAULT, HIGHLIGHT_LIMIT_MAX
from app.services.knowledge_service import KnowledgeService

router = APIRouter(tags=["knowledge"])


def _trigger_jobs_once() -> None:
    thread = threading.Thread(target=get_job_runner().process_available_jobs, daemon=True)
    thread.start()


@router.post(
    "/courses/{course_id}/knowledge/build",
    response_model=KnowledgeBuildResponse,
    status_code=202,
)
async def build_knowledge_framework(
    course_id: str,
    payload: KnowledgeBuildRequest,
) -> KnowledgeBuildResponse:
    with session_scope() as session:
        response = KnowledgeService().start_build(session, course_id=course_id, request=payload)
    _trigger_jobs_once()
    return response


@router.get(
    "/courses/{course_id}/knowledge",
    response_model=KnowledgeFrameworkResponse,
)
async def get_active_knowledge_framework(course_id: str) -> KnowledgeFrameworkResponse:
    with session_scope() as session:
        return KnowledgeService().get_active_framework(session, course_id)


@router.get(
    "/courses/{course_id}/knowledge/graph",
    response_model=KnowledgeGraphResponse,
)
async def get_knowledge_graph(course_id: str) -> KnowledgeGraphResponse:
    with session_scope() as session:
        return KnowledgeService().get_relation_graph(session, course_id)


@router.get(
    "/courses/{course_id}/knowledge/tree",
    response_model=KnowledgeScoredTreeResponse,
)
async def get_scored_knowledge_tree(course_id: str) -> KnowledgeScoredTreeResponse:
    with session_scope() as session:
        return KnowledgeService().get_scored_tree(session, course_id)


@router.get(
    "/courses/{course_id}/knowledge/highlights",
    response_model=KnowledgeHighlightsResponse,
)
async def get_knowledge_highlights(
    course_id: str,
    limit: int = Query(HIGHLIGHT_LIMIT_DEFAULT, ge=1, le=HIGHLIGHT_LIMIT_MAX),
    order: Literal["importance", "difficulty", "gap"] = Query("importance"),
) -> KnowledgeHighlightsResponse:
    with session_scope() as session:
        return KnowledgeService().get_highlights(
            session,
            course_id,
            limit=limit,
            order=order,
        )


@router.get(
    "/knowledge/{knowledge_point_id}",
    response_model=KnowledgeNodeDetailResponse,
)
async def get_knowledge_node(knowledge_point_id: str) -> KnowledgeNodeDetailResponse:
    with session_scope() as session:
        return KnowledgeService().get_node_detail(session, knowledge_point_id)


@router.get(
    "/courses/{course_id}/knowledge/versions",
    response_model=list[KnowledgeVersionResponse],
)
async def list_knowledge_versions(course_id: str) -> list[KnowledgeVersionResponse]:
    with session_scope() as session:
        return KnowledgeService().list_versions(session, course_id)
