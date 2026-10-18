from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.course import Course
from app.repositories.course_repository import CourseRepository
from app.schemas.course import CourseCreateRequest, CourseUpdateRequest


class CourseService:
    def __init__(self, repository: CourseRepository | None = None) -> None:
        self.repository = repository or CourseRepository()

    def list_courses(self, session: Session) -> list[Course]:
        return self.repository.list_courses(session)

    def get_course(self, session: Session, course_id: str) -> Course:
        course = self.repository.get_course(session, course_id)
        if course is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )
        return course

    def create_course(self, session: Session, payload: CourseCreateRequest) -> Course:
        course = self.repository.create_course(
            session,
            name=payload.name.strip(),
            description=payload.description,
        )
        session.commit()
        return course

    def update_course(
        self, session: Session, course_id: str, payload: CourseUpdateRequest
    ) -> Course:
        course = self.get_course(session, course_id)

        if payload.name is not None:
            course.name = payload.name.strip()
        if payload.description is not None:
            course.description = payload.description

        session.commit()
        session.refresh(course)
        return course

    def delete_course(self, session: Session, course_id: str) -> None:
        course = self.get_course(session, course_id)
        self.repository.delete_course(session, course)
        session.commit()

