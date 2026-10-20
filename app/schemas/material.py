from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MaterialUploadResponse(BaseModel):
    document_id: str
    job_id: str | None
    status: str
    error_code: str | None = None


class DocumentParsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str


class MaterialPageResponse(BaseModel):
    page_number: int
    extraction_status: str
    error_code: str | None
    text_preview: str | None
    text_length: int


class MaterialSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    error_code: str | None
    page_count: int
    chunk_count: int
    no_text_pages: list[int]
    created_at: datetime
    updated_at: datetime


class MaterialDetailResponse(MaterialSummaryResponse):
    pages: list[MaterialPageResponse]


class ChunkSearchResult(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_start: int
    page_end: int
    text: str


class ChunkDetailResponse(BaseModel):
    id: str
    document_id: str
    course_id: str
    filename: str
    page_start: int
    page_end: int
    text: str
