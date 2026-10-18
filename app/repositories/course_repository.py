from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.course import Course


class CourseRepository:
    def list_courses(self, session: Session) -> list[Course]:
        statement = select(Course).order_by(Course.created_at.desc())
        return list(session.scalars(statement))

    def get_course(self, session: Session, course_id: str) -> Course | None:
        return session.get(Course, course_id)

    def create_course(
        self, session: Session, *, name: str, description: str | None
    ) -> Course:
        course = Course(name=name, description=description)
        session.add(course)
        session.flush()
        session.refresh(course)
        return course

    def delete_course(self, session: Session, course: Course) -> None:
        session.delete(course)

