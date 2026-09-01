from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "request_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limit_exceeded",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


def build_error_body(
    code: str,
    message: str,
    *,
    details: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details is not None:
        error["details"] = details

    # Keep `detail` for compatibility with existing clients while exposing
    # the stable structured `error` object for new clients.
    return {
        "detail": message,
        "error": error,
    }


def _error_code(status_code: int) -> str:
    return _STATUS_CODES.get(status_code, "http_error")


def _http_message(
    request: Request,
    exc: StarletteHTTPException,
) -> str:
    detail = (
        exc.detail
        if isinstance(exc.detail, str)
        else "Request failed"
    )

    is_development = bool(
        getattr(request.app.state, "is_development", False)
    )

    # Do not expose internal configuration/provider details publicly.
    if exc.status_code >= 500 and not is_development:
        if exc.status_code == 502:
            return "Upstream service error"
        if exc.status_code == 503:
            return "Service temporarily unavailable"
        return "Internal server error"

    return detail


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    message = _http_message(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_body(
            _error_code(exc.status_code),
            message,
        ),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "location": ".".join(
                str(part)
                for part in error.get("loc", ())
            ),
            "message": error.get(
                "msg",
                "Invalid value",
            ),
            "type": error.get(
                "type",
                "validation_error",
            ),
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content=build_error_body(
            "validation_error",
            "Request validation failed",
            details=details,
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Log method/path + traceback, never the request body.
    logger.error(
        "Unhandled request error: %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    return JSONResponse(
        status_code=500,
        content=build_error_body(
            "internal_error",
            "Internal server error",
        ),
    )


def install_error_handlers(application) -> None:
    application.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    application.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    )
