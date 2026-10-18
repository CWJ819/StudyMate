from fastapi import APIRouter
from sqlalchemy import text

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_engine
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


def _check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        current_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))

    head_revisions = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    if current_revision not in head_revisions:
        raise AppError(
            code="DATABASE_SCHEMA_OUTDATED",
            message="Database schema is not at the latest Alembic revision. Run `alembic upgrade head`.",
            status_code=503,
            details={
                "current_revision": current_revision,
                "head_revisions": head_revisions,
            },
        )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    _check_database()
    settings = get_settings()
    return HealthResponse(
        status="ok",
        application="ok",
        database="ok",
        environment=settings.app_env,
    )
