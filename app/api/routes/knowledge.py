import threading
from typing import Literal

from fastapi import APIRouter, Body, Query, Response

from app.db.session import session_scope
from app.jobs.runner import get_job_runner
from app.schemas.knowledge import (
    KnowledgeAliasLockRequest,
    KnowledgeAliasLockResponse,
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeFrameworkResponse,
    KnowledgeGraphResponse,
    KnowledgeHighlightsResponse,
    KnowledgeMergeDecisionsResponse,
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
    "/courses/{course_id}/knowledge/merge-decisions",
    response_model=KnowledgeMergeDecisionsResponse,
)
async def list_knowledge_merge_decisions(
    course_id: str,
) -> KnowledgeMergeDecisionsResponse:
    with session_scope() as session:
        return KnowledgeService().list_merge_decisions(session, course_id)


@router.get(
    "/courses/{course_id}/knowledge/alias-locks",
    response_model=list[KnowledgeAliasLockResponse],
)
async def list_knowledge_alias_locks(
    course_id: str,
) -> list[KnowledgeAliasLockResponse]:
    with session_scope() as session:
        return KnowledgeService().list_alias_locks(session, course_id)


@router.post(
    "/courses/{course_id}/knowledge/alias-locks",
    response_model=KnowledgeAliasLockResponse,
)
async def add_knowledge_alias_lock(
    course_id: str,
    payload: KnowledgeAliasLockRequest,
) -> KnowledgeAliasLockResponse:
    with session_scope() as session:
        return KnowledgeService().add_alias_lock(
            session,
            course_id,
            title_a=payload.title_a,
            title_b=payload.title_b,
        )


@router.post(
    "/courses/{course_id}/knowledge/alias-locks/delete",
    status_code=204,
    response_model=None,
)
async def delete_knowledge_alias_lock_via_post(
    course_id: str,
    payload: KnowledgeAliasLockRequest,
) -> Response:
    """POST alias for ModelScope gateways that reject DELETE (same as course delete)."""
    with session_scope() as session:
        KnowledgeService().delete_alias_lock(
            session, course_id, title_a=payload.title_a, title_b=payload.title_b
        )
    return Response(status_code=204)


@router.delete(
    "/courses/{course_id}/knowledge/alias-locks",
    status_code=204,
    response_model=None,
)
async def delete_knowledge_alias_lock(
    course_id: str,
    payload: KnowledgeAliasLockRequest | None = Body(default=None),
    title_a: str | None = Query(default=None),
    title_b: str | None = Query(default=None),
) -> Response:
    first = payload.title_a if payload is not None else title_a
    second = payload.title_b if payload is not None else title_b
    if first is not None and second is not None:
        with session_scope() as session:
            KnowledgeService().delete_alias_lock(
                session, course_id, title_a=first, title_b=second
            )
    return Response(status_code=204)


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
