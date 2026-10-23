import logging

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.course import Course
from app.repositories.course_repository import CourseRepository
from app.schemas.course import CourseCreateRequest, CourseUpdateRequest
from app.storage.local import LocalStorage

logger = logging.getLogger(__name__)


class CourseService:
    def __init__(
        self,
        repository: CourseRepository | None = None,
        storage: LocalStorage | None = None,
    ) -> None:
        self.repository = repository or CourseRepository()
        self.storage = storage or LocalStorage()

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
        storage_keys = list(
            dict.fromkeys(
                document.storage_key
                for document in course.documents
                if document.storage_key
            )
        )
        self.repository.delete_course(session, course)
        session.commit()
        for storage_key in storage_keys:
            try:
                self.storage.delete(storage_key)
            except Exception:
                logger.warning(
                    "Failed to delete course document from storage; leaving orphan file",
                    extra={"course_id": course_id, "storage_key": storage_key},
                )

