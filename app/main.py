import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIDMiddleware
from app.db.session import dispose_engine
from app.jobs.runner import run_worker_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    get_settings().storage_root.mkdir(parents=True, exist_ok=True)
    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(run_worker_loop(stop_event))
    yield
    stop_event.set()
    await worker_task
    dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="StudyMate Backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(api_router, prefix="/api")
    register_exception_handlers(app)
    return app


app = create_app()
