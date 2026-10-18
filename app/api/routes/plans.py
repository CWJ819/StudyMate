from fastapi import APIRouter

from app.db.session import session_scope
from app.schemas.plan import (
    StudyPlanDetailResponse,
    StudyPlanGenerateRequest,
    StudyPlanSummaryResponse,
    StudyTaskResponse,
    StudyTaskUpdateRequest,
)
from app.services.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.post(
    "/courses/{course_id}/plan",
    response_model=StudyPlanDetailResponse,
    status_code=201,
)
async def generate_study_plan(
    course_id: str,
    payload: StudyPlanGenerateRequest,
) -> StudyPlanDetailResponse:
    with session_scope() as session:
        return PlanService().generate_plan(session, course_id=course_id, request=payload)


@router.get(
    "/courses/{course_id}/plans",
    response_model=list[StudyPlanSummaryResponse],
)
async def list_study_plans(course_id: str) -> list[StudyPlanSummaryResponse]:
    with session_scope() as session:
        return PlanService().list_plans(session, course_id)


@router.get(
    "/plans/{plan_id}",
    response_model=StudyPlanDetailResponse,
)
async def get_study_plan(plan_id: str) -> StudyPlanDetailResponse:
    with session_scope() as session:
        return PlanService().get_plan(session, plan_id)


@router.patch(
    "/tasks/{task_id}",
    response_model=StudyTaskResponse,
)
async def update_study_task(
    task_id: str,
    payload: StudyTaskUpdateRequest,
) -> StudyTaskResponse:
    with session_scope() as session:
        return PlanService().update_task(session, task_id=task_id, request=payload)
