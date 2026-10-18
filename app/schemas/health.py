from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    application: str
    database: str
    environment: str

