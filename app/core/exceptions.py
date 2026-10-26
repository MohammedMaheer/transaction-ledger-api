"""Public errors contain no SQL, connection strings, or raw request values."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class LedgerError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


ERROR_RESPONSES = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Invalid business operation",
        404: "Account or route not found",
        409: "Reference or concurrent operation conflict",
        422: "Invalid request data",
        500: "Unexpected internal failure",
        503: "Database temporarily unavailable",
    }.items()
}


def error_response(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LedgerError)
    async def ledger_error_handler(request: Request, exc: LedgerError):
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Pydantic's input/ctx may include secrets or non-serializable exceptions.
        errors = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return error_response(
            422, "VALIDATION_ERROR", "Request validation failed", {"errors": errors}
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        response = error_response(
            exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        return error_response(409, "INTEGRITY_CONFLICT", "Operation violates a database constraint")

    @app.exception_handler(DBAPIError)
    async def database_error_handler(request: Request, exc: DBAPIError):
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate in {"40001", "40P01", "55P03", "57014"}:
            return error_response(
                409, "CONCURRENT_OPERATION", "Operation conflicted; retry the request"
            )
        logger.error("Database request failed (%s)", type(exc.orig).__name__)
        return error_response(503, "DATABASE_UNAVAILABLE", "Database temporarily unavailable")

    @app.exception_handler(ConnectionError)
    @app.exception_handler(TimeoutError)
    @app.exception_handler(PoolTimeoutError)
    async def connection_error_handler(request: Request, exc: Exception):
        logger.error("Database connection failed (%s)", type(exc).__name__)
        return error_response(503, "DATABASE_UNAVAILABLE", "Database temporarily unavailable")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error("Unexpected request failure (%s)", type(exc).__name__)
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
