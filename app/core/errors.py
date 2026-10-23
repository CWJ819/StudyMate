from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


_SECRET_FIELD_MARKERS = ("key", "token", "secret")


def _masked_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Never echo a secret-shaped request value back in a 422 response.

    Pydantic's ``extra_forbidden`` error carries the whole input object in
    ``input`` when a field name is misspelled (e.g. ``apiKey``).  Masking the
    input for any error location touching key/token/secret closes that leak
    while keeping the field path intact for the client.
    """
    masked: list[dict[str, Any]] = []
    for error in exc.errors():
        item = dict(error)
        location = ".".join(str(part).lower() for part in item.get("loc", ()))
        if any(marker in location for marker in _SECRET_FIELD_MARKERS):
            item["input"] = "***"
        masked.append(item)
    return masked


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details={"errors": _masked_validation_errors(exc)},
    )


async def integrity_error_handler(request: Request, _: IntegrityError) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=409,
        code="IDEMPOTENCY_CONFLICT",
        message="A conflicting record already exists.",
    )


async def database_busy_handler(request: Request, _: OperationalError) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=503,
        code="DATABASE_BUSY",
        message="Database is busy; please retry.",
        details={"retryable": True},
    )


async def unhandled_error_handler(request: Request, _: Exception) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(OperationalError, database_busy_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

