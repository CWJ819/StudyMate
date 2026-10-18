from fastapi import APIRouter

from app.api.routes.courses import router as courses_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.mastery import router as mastery_router
from app.api.routes.materials import router as materials_router
from app.api.routes.plans import router as plans_router
from app.api.routes.quizzes import router as quizzes_router
from app.api.routes.settings import router as settings_router

api_router = APIRouter()
api_router.include_router(courses_router)
api_router.include_router(health_router)
api_router.include_router(jobs_router)
api_router.include_router(knowledge_router)
api_router.include_router(mastery_router)
api_router.include_router(materials_router)
api_router.include_router(plans_router)
api_router.include_router(quizzes_router)
api_router.include_router(settings_router)
