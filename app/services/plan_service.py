from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models.knowledge import KnowledgeNodeVersion
from app.db.models.plan import StudyPlan, StudyTask
from app.repositories.plan_repository import PlanRepository
from app.schemas.plan import (
    StudyPlanDetailResponse,
    StudyPlanGenerateRequest,
    StudyPlanSummaryResponse,
    StudyTaskResponse,
    StudyTaskTargetResponse,
    StudyTaskUpdateRequest,
)

PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_INACTIVE = "inactive"
TASK_STATUS_PENDING = "pending"
TASK_STATUS_IN_PROGRESS = "in_progress"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_SKIPPED = "skipped"

ALLOWED_TASK_STATUS_TRANSITIONS = {
    TASK_STATUS_PENDING: {TASK_STATUS_PENDING, TASK_STATUS_IN_PROGRESS, TASK_STATUS_COMPLETED, TASK_STATUS_SKIPPED},
    TASK_STATUS_IN_PROGRESS: {TASK_STATUS_IN_PROGRESS, TASK_STATUS_COMPLETED, TASK_STATUS_SKIPPED},
    TASK_STATUS_COMPLETED: {TASK_STATUS_COMPLETED},
    TASK_STATUS_SKIPPED: {TASK_STATUS_SKIPPED},
}


class PlanService:
    def __init__(self, repository: PlanRepository | None = None) -> None:
        self.repository = repository or PlanRepository()

    def generate_plan(
        self,
        session: Session,
        *,
        course_id: str,
        request: StudyPlanGenerateRequest,
    ) -> StudyPlanDetailResponse:
        self._require_course(session, course_id)
        today = datetime.now(UTC).date()
        if request.exam_date < today:
            raise AppError(
                code="INVALID_PLAN_CONSTRAINTS",
                message="Exam date must be today or later.",
                status_code=400,
                details={"exam_date": request.exam_date.isoformat()},
            )

        nodes = self.repository.list_active_leaf_nodes(
            session,
            course_id,
            knowledge_node_ids=request.knowledge_node_ids or None,
        )
        if not nodes:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="No active leaf knowledge nodes are available for plan generation.",
                status_code=404,
                details={"course_id": course_id},
            )
        if request.knowledge_node_ids:
            found_ids = {node.knowledge_node_id for node in nodes}
            missing = sorted(set(request.knowledge_node_ids) - found_ids)
            if missing:
                raise AppError(
                    code="RESOURCE_NOT_FOUND",
                    message="Some requested knowledge nodes are not present in the active framework.",
                    status_code=404,
                    details={"knowledge_node_ids": missing},
                )

        task_specs = self._build_task_specs(nodes, daily_minutes=request.daily_minutes)
        schedule = self._schedule_tasks(
            task_specs,
            start_date=today,
            end_date=request.exam_date,
            daily_minutes=request.daily_minutes,
        )

        self.repository.deactivate_active_plans(session, course_id)
        plan = self.repository.create_plan(
            session,
            course_id=course_id,
            version_number=self.repository.next_version_number(session, course_id),
            exam_date=request.exam_date,
            daily_minutes=request.daily_minutes,
            target_score=request.target_score,
            status=PLAN_STATUS_ACTIVE,
            constraints_json={
                "knowledge_node_ids": request.knowledge_node_ids,
                "generated_at": datetime.now(UTC).isoformat(),
                "algorithm_version": "study-plan-v1",
            },
        )
        for scheduled_date, spec in schedule:
            task = self.repository.add_task(
                session,
                plan_id=plan.id,
                title=spec["title"],
                task_type=spec["task_type"],
                scheduled_date=scheduled_date,
                estimated_minutes=spec["estimated_minutes"],
                priority=spec["priority"],
                status=TASK_STATUS_PENDING,
            )
            self.repository.add_task_target(
                session,
                task_id=task.id,
                knowledge_node_id=spec["knowledge_node_id"],
                target_role=spec["target_role"],
            )
        session.commit()
        refreshed = self.repository.get_plan(session, plan.id)
        assert refreshed is not None
        return self._plan_detail(refreshed)

    def list_plans(self, session: Session, course_id: str) -> list[StudyPlanSummaryResponse]:
        self._require_course(session, course_id)
        return [self._plan_summary(plan) for plan in self.repository.list_plans(session, course_id)]

    def get_plan(self, session: Session, plan_id: str) -> StudyPlanDetailResponse:
        plan = self.repository.get_plan(session, plan_id)
        if plan is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Study plan not found.",
                status_code=404,
                details={"plan_id": plan_id},
            )
        return self._plan_detail(plan)

    def update_task(
        self,
        session: Session,
        *,
        task_id: str,
        request: StudyTaskUpdateRequest,
    ) -> StudyTaskResponse:
        task = self.repository.get_task(session, task_id)
        if task is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Study task not found.",
                status_code=404,
                details={"task_id": task_id},
            )
        if request.status not in ALLOWED_TASK_STATUS_TRANSITIONS:
            raise AppError(
                code="INVALID_TASK_STATUS",
                message="Study task status is not supported.",
                status_code=400,
                details={"status": request.status},
            )
        allowed = ALLOWED_TASK_STATUS_TRANSITIONS.get(task.status, {task.status})
        if request.status not in allowed:
            raise AppError(
                code="INVALID_TASK_STATUS_TRANSITION",
                message="Study task status transition is not allowed.",
                status_code=409,
                details={"from": task.status, "to": request.status},
            )
        task.status = request.status
        session.commit()
        refreshed = self.repository.get_task(session, task.id)
        assert refreshed is not None
        return self._task_response(refreshed)

    def _build_task_specs(
        self,
        nodes: list[KnowledgeNodeVersion],
        *,
        daily_minutes: int,
    ) -> list[dict]:
        estimated_minutes = min(30, max(15, daily_minutes))
        specs: list[dict] = []
        for index, node in enumerate(nodes, start=1):
            specs.append(
                {
                    "title": f"Review {node.title}",
                    "task_type": "review",
                    "estimated_minutes": estimated_minutes,
                    "priority": index,
                    "knowledge_node_id": node.knowledge_node_id,
                    "target_role": "primary",
                }
            )
            specs.append(
                {
                    "title": f"Practice {node.title}",
                    "task_type": "practice",
                    "estimated_minutes": estimated_minutes,
                    "priority": index + len(nodes),
                    "knowledge_node_id": node.knowledge_node_id,
                    "target_role": "practice",
                }
            )
        return specs

    def _schedule_tasks(
        self,
        task_specs: list[dict],
        *,
        start_date: date,
        end_date: date,
        daily_minutes: int,
    ) -> list[tuple[date, dict]]:
        available_days = (end_date - start_date).days + 1
        capacity = available_days * daily_minutes
        required = sum(spec["estimated_minutes"] for spec in task_specs)
        if required > capacity:
            raise AppError(
                code="PLAN_CAPACITY_EXCEEDED",
                message="The requested plan cannot fit before the exam date within daily minutes.",
                status_code=409,
                details={"required_minutes": required, "available_minutes": capacity},
            )

        scheduled: list[tuple[date, dict]] = []
        daily_totals: dict[date, int] = defaultdict(int)
        current_day = start_date
        for spec in task_specs:
            while daily_totals[current_day] + spec["estimated_minutes"] > daily_minutes:
                current_day += timedelta(days=1)
                if current_day > end_date:
                    raise AppError(
                        code="PLAN_CAPACITY_EXCEEDED",
                        message="The requested plan cannot fit before the exam date within daily minutes.",
                        status_code=409,
                    )
            scheduled.append((current_day, spec))
            daily_totals[current_day] += spec["estimated_minutes"]
        return scheduled

    def _plan_summary(self, plan: StudyPlan) -> StudyPlanSummaryResponse:
        return StudyPlanSummaryResponse(
            id=plan.id,
            course_id=plan.course_id,
            version_number=plan.version_number,
            exam_date=plan.exam_date,
            daily_minutes=plan.daily_minutes,
            target_score=plan.target_score,
            status=plan.status,
            task_count=len(plan.tasks),
            created_at=plan.created_at,
        )

    def _plan_detail(self, plan: StudyPlan) -> StudyPlanDetailResponse:
        return StudyPlanDetailResponse(
            id=plan.id,
            course_id=plan.course_id,
            version_number=plan.version_number,
            exam_date=plan.exam_date,
            daily_minutes=plan.daily_minutes,
            target_score=plan.target_score,
            status=plan.status,
            constraints=plan.constraints_json,
            created_at=plan.created_at,
            tasks=[self._task_response(task) for task in sorted(plan.tasks, key=self._task_sort_key)],
        )

    def _task_response(self, task: StudyTask) -> StudyTaskResponse:
        return StudyTaskResponse(
            id=task.id,
            title=task.title,
            task_type=task.task_type,
            scheduled_date=task.scheduled_date,
            estimated_minutes=task.estimated_minutes,
            priority=task.priority,
            status=task.status,
            targets=[
                StudyTaskTargetResponse(
                    knowledge_node_id=target.knowledge_node_id,
                    title=target.knowledge_node.stable_key if target.knowledge_node else None,
                    target_role=target.target_role,
                )
                for target in task.targets
            ],
        )

    def _task_sort_key(self, task: StudyTask) -> tuple[date, int, str]:
        return (task.scheduled_date, task.priority, task.id)

    def _require_course(self, session: Session, course_id: str) -> None:
        if self.repository.get_course(session, course_id) is None:
            raise AppError(
                code="RESOURCE_NOT_FOUND",
                message="Course not found.",
                status_code=404,
                details={"course_id": course_id},
            )
