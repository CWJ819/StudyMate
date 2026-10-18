from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.course import Course
from app.db.models.knowledge import KnowledgeFrameworkVersion, KnowledgeNodeVersion
from app.db.models.plan import StudyPlan, StudyTask, StudyTaskTarget


class PlanRepository:
    def get_course(self, session: Session, course_id: str) -> Course | None:
        return session.get(Course, course_id)

    def next_version_number(self, session: Session, course_id: str) -> int:
        current = session.scalar(
            select(func.max(StudyPlan.version_number)).where(StudyPlan.course_id == course_id)
        )
        return int(current or 0) + 1

    def create_plan(
        self,
        session: Session,
        *,
        course_id: str,
        version_number: int,
        exam_date,
        daily_minutes: int,
        target_score: int,
        status: str,
        constraints_json: dict,
    ) -> StudyPlan:
        plan = StudyPlan(
            course_id=course_id,
            version_number=version_number,
            exam_date=exam_date,
            daily_minutes=daily_minutes,
            target_score=target_score,
            status=status,
            constraints_json=constraints_json,
        )
        session.add(plan)
        session.flush()
        session.refresh(plan)
        return plan

    def deactivate_active_plans(self, session: Session, course_id: str) -> None:
        for plan in session.scalars(
            select(StudyPlan)
            .where(StudyPlan.course_id == course_id)
            .where(StudyPlan.status == "active")
        ):
            plan.status = "inactive"

    def add_task(
        self,
        session: Session,
        *,
        plan_id: str,
        title: str,
        task_type: str,
        scheduled_date,
        estimated_minutes: int,
        priority: int,
        status: str,
    ) -> StudyTask:
        task = StudyTask(
            plan_id=plan_id,
            title=title,
            task_type=task_type,
            scheduled_date=scheduled_date,
            estimated_minutes=estimated_minutes,
            priority=priority,
            status=status,
        )
        session.add(task)
        session.flush()
        session.refresh(task)
        return task

    def add_task_target(
        self,
        session: Session,
        *,
        task_id: str,
        knowledge_node_id: str,
        target_role: str,
    ) -> StudyTaskTarget:
        target = StudyTaskTarget(
            task_id=task_id,
            knowledge_node_id=knowledge_node_id,
            target_role=target_role,
        )
        session.add(target)
        session.flush()
        return target

    def list_active_leaf_nodes(
        self,
        session: Session,
        course_id: str,
        *,
        knowledge_node_ids: list[str] | None = None,
    ) -> list[KnowledgeNodeVersion]:
        active_id = session.scalar(
            select(KnowledgeFrameworkVersion.id)
            .where(KnowledgeFrameworkVersion.course_id == course_id)
            .where(KnowledgeFrameworkVersion.status == "active")
            .order_by(KnowledgeFrameworkVersion.version_number.desc())
            .limit(1)
        )
        if active_id is None:
            return []
        statement = (
            select(KnowledgeNodeVersion)
            .where(KnowledgeNodeVersion.framework_version_id == active_id)
            .where(KnowledgeNodeVersion.is_leaf.is_(True))
            .order_by(KnowledgeNodeVersion.level.asc(), KnowledgeNodeVersion.sort_order.asc())
        )
        if knowledge_node_ids:
            statement = statement.where(KnowledgeNodeVersion.knowledge_node_id.in_(knowledge_node_ids))
        return list(session.scalars(statement))

    def list_plans(self, session: Session, course_id: str) -> list[StudyPlan]:
        statement = (
            select(StudyPlan)
            .where(StudyPlan.course_id == course_id)
            .options(selectinload(StudyPlan.tasks))
            .order_by(StudyPlan.version_number.desc())
        )
        return list(session.scalars(statement))

    def get_plan(self, session: Session, plan_id: str) -> StudyPlan | None:
        statement = (
            select(StudyPlan)
            .where(StudyPlan.id == plan_id)
            .options(
                selectinload(StudyPlan.tasks)
                .selectinload(StudyTask.targets)
                .selectinload(StudyTaskTarget.knowledge_node)
            )
        )
        return session.scalar(statement)

    def get_task(self, session: Session, task_id: str) -> StudyTask | None:
        statement = (
            select(StudyTask)
            .where(StudyTask.id == task_id)
            .options(
                selectinload(StudyTask.targets).selectinload(StudyTaskTarget.knowledge_node),
                selectinload(StudyTask.plan),
            )
        )
        return session.scalar(statement)
