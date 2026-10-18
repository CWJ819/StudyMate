from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


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


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details={"errors": exc.errors()},
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
    app.add_exception_handler(Exception, unhandled_error_handler)

