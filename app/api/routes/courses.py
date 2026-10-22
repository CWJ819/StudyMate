from fastapi import APIRouter

from app.db.session import session_scope
from app.schemas.course import CourseCreateRequest, CourseResponse, CourseUpdateRequest
from app.services.course_service import CourseService

router = APIRouter(tags=["courses"])
service = CourseService()


@router.post("/courses", response_model=CourseResponse, status_code=201)
async def create_course(payload: CourseCreateRequest) -> CourseResponse:
    with session_scope() as session:
        course = service.create_course(session, payload)
        return CourseResponse.model_validate(course)


@router.get("/courses", response_model=list[CourseResponse])
async def list_courses() -> list[CourseResponse]:
    with session_scope() as session:
        courses = service.list_courses(session)
        return [CourseResponse.model_validate(course) for course in courses]


@router.get("/courses/{course_id}", response_model=CourseResponse)
async def get_course(course_id: str) -> CourseResponse:
    with session_scope() as session:
        course = service.get_course(session, course_id)
        return CourseResponse.model_validate(course)


@router.patch("/courses/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: str, payload: CourseUpdateRequest
) -> CourseResponse:
    with session_scope() as session:
        course = service.update_course(session, course_id, payload)
        return CourseResponse.model_validate(course)


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(course_id: str) -> None:
    with session_scope() as session:
        service.delete_course(session, course_id)


@router.post("/courses/{course_id}/delete", status_code=204)
async def delete_course_via_post(course_id: str) -> None:
    """ModelScope's API gateway rejects DELETE; the SPA uses this POST alias."""
    with session_scope() as session:
        service.delete_course(session, course_id)
