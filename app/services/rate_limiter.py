import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


class FixedWindowRateLimiter:
    """Small in-memory fixed-window limiter for a single app process."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds < 1:
            raise ValueError(
                "window_seconds must be at least 1"
            )

        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()

        with self._lock:
            window_start, count = self._buckets.get(
                key,
                (now, 0),
            )

            elapsed = now - window_start
            if elapsed >= self.window_seconds:
                window_start = now
                count = 0
                elapsed = 0.0

            reset_after = max(
                1,
                math.ceil(
                    self.window_seconds - elapsed
                ),
            )

            if count >= self.limit:
                return RateLimitDecision(
                    allowed=False,
                    limit=self.limit,
                    remaining=0,
                    reset_after_seconds=reset_after,
                )

            count += 1
            self._buckets[key] = (window_start, count)

            # Bound stale-key growth for long-running single-process use.
            if len(self._buckets) > 1024:
                stale_before = now - self.window_seconds
                self._buckets = {
                    bucket_key: value
                    for bucket_key, value
                    in self._buckets.items()
                    if value[0] > stale_before
                }

            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=max(
                    self.limit - count,
                    0,
                ),
                reset_after_seconds=reset_after,
            )


class ChatRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limits only to POST /api/v1/chat requests."""

    def __init__(
        self,
        app,
        *,
        limiter: FixedWindowRateLimiter,
    ):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        if not (
            request.method == "POST"
            and request.url.path == "/api/v1/chat"
        ):
            return await call_next(request)

        # Deliberately use the socket peer address. X-Forwarded-For is not
        # trusted unless a deployment has a configured trusted proxy layer.
        client_key = (
            request.client.host
            if request.client is not None
            else "unknown"
        )

        decision = self.limiter.check(client_key)
        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(
                decision.remaining
            ),
            "X-RateLimit-Reset": str(
                decision.reset_after_seconds
            ),
        }

        if not decision.allowed:
            headers["Retry-After"] = str(
                decision.reset_after_seconds
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded"
                },
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response
