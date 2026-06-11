"""
Global exception handlers.
Every error response leaves the API in one envelope:
{"success": false, "error": {"code": ..., "message": ..., ...}}.
"""

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

logger = logging.getLogger(__name__)

# Fallback codes for routes that raise plain-string details.
_STATUS_FALLBACK_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
}


def error_envelope(code: str, message: str, extra: dict | None = None) -> dict:
    """Build the canonical error response body."""
    error: dict = {"code": code, "message": message}
    if extra:
        error.update(extra)
    return {"success": False, "error": error}


def _fallback_code(status_code: int) -> str:
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return _STATUS_FALLBACK_CODES.get(status_code, "ERROR")


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error path emits the canonical envelope."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code") or _fallback_code(exc.status_code)
            message = detail.get("message") or "Request failed."
            extra = {k: v for k, v in detail.items() if k not in ("code", "message")}
        else:
            code = _fallback_code(exc.status_code)
            message = str(detail)
            extra = None

        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code, message, extra),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        msg = first.get("msg", "Invalid request")
        message = f"{field}: {msg}" if field else msg

        return JSONResponse(
            status_code=422,
            content=error_envelope("VALIDATION_ERROR", message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Never leak internals; the traceback goes to the logs only.
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content=error_envelope(
                "INTERNAL_ERROR",
                "Something went wrong on our side. Please try again.",
            ),
        )
