from fastapi import APIRouter

from app.db.session import session_scope
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest
from app.services.settings_service import SettingsService

router = APIRouter(tags=["settings"])
service = SettingsService()


@router.get("/settings", response_model=SettingsResponse)
async def read_settings() -> SettingsResponse:
    with session_scope() as session:
        return service.read_settings(session)


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(payload: SettingsUpdateRequest) -> SettingsResponse:
    with session_scope() as session:
        return service.update_settings(session, payload)
