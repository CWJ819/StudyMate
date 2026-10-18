import threading

from fastapi import APIRouter, status

from app.db.session import session_scope
from app.jobs.runner import get_job_runner
from app.schemas.quiz import (
    QuizDetailResponse,
    QuizGenerateRequest,
    QuizGenerateResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
)
from app.services.quiz_service import QuizService

router = APIRouter(tags=["quizzes"])


def _trigger_jobs_once() -> None:
    thread = threading.Thread(target=get_job_runner().process_available_jobs, daemon=True)
    thread.start()


@router.post(
    "/courses/{course_id}/quiz/generate",
    response_model=QuizGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_quiz(course_id: str, payload: QuizGenerateRequest) -> QuizGenerateResponse:
    with session_scope() as session:
        response = QuizService().start_generate(session, course_id=course_id, request=payload)
    _trigger_jobs_once()
    return response


@router.get("/quizzes/{quiz_id}", response_model=QuizDetailResponse)
async def get_quiz(quiz_id: str) -> QuizDetailResponse:
    with session_scope() as session:
        return QuizService().get_quiz(session, quiz_id)


@router.post(
    "/quizzes/{quiz_id}/submit",
    response_model=QuizSubmitResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_quiz(quiz_id: str, payload: QuizSubmitRequest) -> QuizSubmitResponse:
    with session_scope() as session:
        return QuizService().submit_quiz(session, quiz_id=quiz_id, request=payload)
