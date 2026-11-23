"""Uniform error envelope: {"error": {"code": str, "message": str, "details"?: any}}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from androai_storage import InvalidKey

log = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code, self.code, self.message = status_code, code, message
        super().__init__(message)


def _body(code: str, message: str, details=None) -> dict:
    err: dict = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    return {"error": err}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse(
            _body(f"http_{exc.status_code}", str(exc.detail)), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            _body("validation_error", "Invalid request", exc.errors()), status_code=422
        )

    @app.exception_handler(InvalidKey)
    async def _invalid_key(request: Request, exc: InvalidKey):
        # A storage key outside the caller's tenant scope means corrupted data or an attack.
        log.error("SECURITY storage key rejected path=%s reason=%s", request.url.path, exc)
        return JSONResponse(_body("forbidden", "Access denied"), status_code=403)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse(_body("internal_error", "Internal server error"), status_code=500)
