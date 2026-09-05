import hashlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from redis import Redis
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..core.errors import build_error_body
from ..core.observability import log_event
from ..core.routes import PUBLIC_GATEWAY_POST_PATHS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


class RateLimiter(Protocol):
    def check(self, key: str) -> RateLimitDecision:
        ...

    def ping(self) -> bool:
        ...


class FixedWindowRateLimiter:
    """Small in-memory fixed-window limiter for one app process."""

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
            raise ValueError("window_seconds must be at least 1")

        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()

        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            elapsed = now - window_start

            if elapsed >= self.window_seconds:
                window_start = now
                count = 0
                elapsed = 0.0

            reset_after = max(
                1,
                math.ceil(self.window_seconds - elapsed),
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

            if len(self._buckets) > 1024:
                stale_before = now - self.window_seconds
                self._buckets = {
                    bucket_key: value
                    for bucket_key, value in self._buckets.items()
                    if value[0] > stale_before
                }

            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=max(self.limit - count, 0),
                reset_after_seconds=reset_after,
            )

    def ping(self) -> bool:
        return True


class RedisFixedWindowRateLimiter:
    """Atomic shared fixed-window limiter backed by Redis."""

    _INCREMENT_SCRIPT = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    local ttl = redis.call('TTL', KEYS[1])
    return {current, ttl}
    """

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        redis_url: str | None = None,
        client=None,
        key_prefix: str = "llmbastion:rate_limit",
    ):
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")
        if client is None and not redis_url:
            raise ValueError(
                "redis_url is required when no Redis client is supplied"
            )

        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.client = client or Redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )

    def _redis_key(self, client_key: str) -> str:
        digest = hashlib.sha256(client_key.encode("utf-8")).hexdigest()
        return f"{self.key_prefix}:{digest}"

    def check(self, key: str) -> RateLimitDecision:
        redis_key = self._redis_key(key)
        result = self.client.eval(
            self._INCREMENT_SCRIPT,
            1,
            redis_key,
            self.window_seconds,
        )

        count = int(result[0])
        ttl = max(int(result[1]), 1)

        return RateLimitDecision(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=max(self.limit - count, 0),
            reset_after_seconds=ttl,
        )

    def ping(self) -> bool:
        return bool(self.client.ping())


def build_rate_limiter(
    *,
    backend: str,
    limit: int,
    window_seconds: int,
    redis_url: str | None = None,
) -> RateLimiter:
    normalized_backend = backend.strip().lower()

    if normalized_backend == "memory":
        return FixedWindowRateLimiter(
            limit=limit,
            window_seconds=window_seconds,
        )

    if normalized_backend == "redis":
        return RedisFixedWindowRateLimiter(
            limit=limit,
            window_seconds=window_seconds,
            redis_url=redis_url,
        )

    raise ValueError("backend must be either 'memory' or 'redis'")


class ChatRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limits to public LLM gateway endpoints."""

    def __init__(self, app, *, limiter: RateLimiter):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        if not (
            request.method == "POST"
            and request.url.path in PUBLIC_GATEWAY_POST_PATHS
        ):
            return await call_next(request)

        client_key = (
            request.client.host
            if request.client is not None
            else "unknown"
        )

        try:
            decision = await run_in_threadpool(
                self.limiter.check,
                client_key,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "rate_limit.backend_unavailable",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            return JSONResponse(
                status_code=503,
                content=build_error_body(
                    "rate_limiter_unavailable",
                    "Rate limiter temporarily unavailable",
                ),
            )

        headers = {
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_after_seconds),
        }

        if not decision.allowed:
            headers["Retry-After"] = str(decision.reset_after_seconds)
            return JSONResponse(
                status_code=429,
                content=build_error_body(
                    "rate_limit_exceeded",
                    "Rate limit exceeded",
                ),
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response
