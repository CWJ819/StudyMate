import threading

from fastapi import APIRouter, File, Query, UploadFile, status

from app.db.session import session_scope
from app.jobs.runner import get_job_runner
from app.schemas.material import (
    ChunkDetailResponse,
    ChunkSearchResult,
    MaterialDetailResponse,
    MaterialSummaryResponse,
    MaterialUploadResponse,
)
from app.services.material_service import MaterialService

router = APIRouter(tags=["materials"])


def _trigger_jobs_once() -> None:
    thread = threading.Thread(target=get_job_runner().process_available_jobs, daemon=True)
    thread.start()


@router.post(
    "/courses/{course_id}/materials",
    response_model=MaterialUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material(
    course_id: str,
    file: UploadFile = File(...),
) -> MaterialUploadResponse:
    try:
        data = await file.read()
        with session_scope() as session:
            response = MaterialService().upload_material(
                session,
                course_id=course_id,
                filename=file.filename or "upload.bin",
                content_type=file.content_type,
                data=data,
            )
        _trigger_jobs_once()
        return response
    finally:
        await file.close()


@router.get(
    "/courses/{course_id}/materials",
    response_model=list[MaterialSummaryResponse],
)
async def list_materials(course_id: str) -> list[MaterialSummaryResponse]:
    with session_scope() as session:
        return MaterialService().list_materials(session, course_id)


@router.get("/materials/{material_id}", response_model=MaterialDetailResponse)
async def get_material(material_id: str) -> MaterialDetailResponse:
    with session_scope() as session:
        return MaterialService().get_material(session, material_id)


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(material_id: str) -> None:
    with session_scope() as session:
        MaterialService().delete_material(session, material_id)


@router.get(
    "/courses/{course_id}/search",
    response_model=list[ChunkSearchResult],
)
async def search_materials(
    course_id: str,
    q: str = Query(min_length=1),
) -> list[ChunkSearchResult]:
    with session_scope() as session:
        return MaterialService().search_materials(session, course_id=course_id, query=q)


@router.get("/chunks/{chunk_id}", response_model=ChunkDetailResponse)
async def get_chunk(chunk_id: str) -> ChunkDetailResponse:
    with session_scope() as session:
        return MaterialService().get_chunk(session, chunk_id)
