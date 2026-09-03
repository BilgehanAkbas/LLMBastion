from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..core.observability import (
    bind_request_id,
    log_event,
    reset_request_id,
    safe_request_path,
)

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Create one server-owned correlation ID for every HTTP request."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        # Do not trust a public X-Request-ID as a database/log identifier.
        # We generate a canonical UUID that also fits requests.request_id.
        request_id = str(uuid4())
        token = bind_request_id(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (
                time.perf_counter() - started
            ) * 1000
            log_event(
                logger,
                logging.ERROR,
                "http.request_failed",
                method=request.method,
                path=safe_request_path(request),
                status_code=500,
                duration_ms=round(duration_ms, 3),
                exc_info=(
                    type(exc),
                    exc,
                    exc.__traceback__,
                ),
            )
            raise
        else:
            response.headers["X-Request-ID"] = request_id

            # Static files are intentionally excluded from access-style logs
            # to keep operational logs focused and low-noise.
            safe_path = safe_request_path(request)
            if not safe_path.startswith("/static/"):
                duration_ms = (
                    time.perf_counter() - started
                ) * 1000
                log_event(
                    logger,
                    logging.INFO,
                    "http.request_complete",
                    method=request.method,
                    path=safe_path,
                    status_code=response.status_code,
                    duration_ms=round(duration_ms, 3),
                )

            return response
        finally:
            reset_request_id(token)
