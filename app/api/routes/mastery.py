from fastapi import APIRouter

from app.db.session import session_scope
from app.schemas.mastery import (
    KnowledgeGapResponse,
    MasteryStateResponse,
    MasteryOverviewResponse,
    ReviewTargetsRequest,
    ReviewTargetsResponse,
)
from app.services.mastery_service import MasteryService

router = APIRouter(tags=["mastery"])


@router.get(
    "/courses/{course_id}/mastery",
    response_model=list[MasteryStateResponse],
)
async def list_mastery(course_id: str) -> list[MasteryStateResponse]:
    with session_scope() as session:
        return MasteryService().list_mastery(session, course_id)


@router.get(
    "/courses/{course_id}/mastery/overview",
    response_model=MasteryOverviewResponse,
)
async def mastery_overview(course_id: str) -> MasteryOverviewResponse:
    with session_scope() as session:
        return MasteryService().mastery_overview(session, course_id)


@router.get(
    "/courses/{course_id}/wrongbook",
    response_model=list[KnowledgeGapResponse],
)
async def list_wrongbook(course_id: str) -> list[KnowledgeGapResponse]:
    with session_scope() as session:
        return MasteryService().list_wrongbook(session, course_id)


@router.post(
    "/courses/{course_id}/review-targets",
    response_model=ReviewTargetsResponse,
)
async def select_review_targets(
    course_id: str,
    payload: ReviewTargetsRequest,
) -> ReviewTargetsResponse:
    with session_scope() as session:
        return MasteryService().select_review_targets(
            session,
            course_id=course_id,
            request=payload,
        )
