import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.rate_limiter import (
    ChatRateLimitMiddleware,
    FixedWindowRateLimiter,
    RedisFixedWindowRateLimiter,
    build_rate_limiter,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeRedis:
    def __init__(self, eval_results=None, ping_result=True):
        self.eval_results = list(
            eval_results or []
        )
        self.ping_result = ping_result
        self.eval_calls = []

    def eval(self, *args):
        self.eval_calls.append(args)
        return self.eval_results.pop(0)

    def ping(self):
        return self.ping_result


def test_limiter_allows_requests_within_window():
    clock = FakeClock()
    limiter = FixedWindowRateLimiter(
        limit=2,
        window_seconds=60,
        clock=clock,
    )

    first = limiter.check("client-a")
    second = limiter.check("client-a")

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0


def test_limiter_rejects_after_limit():
    clock = FakeClock()
    limiter = FixedWindowRateLimiter(
        limit=1,
        window_seconds=60,
        clock=clock,
    )

    assert limiter.check("client-a").allowed is True

    blocked = limiter.check("client-a")

    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.reset_after_seconds == 60


def test_limiter_resets_after_window():
    clock = FakeClock()
    limiter = FixedWindowRateLimiter(
        limit=1,
        window_seconds=10,
        clock=clock,
    )

    limiter.check("client-a")
    assert limiter.check("client-a").allowed is False

    clock.advance(10)

    reset = limiter.check("client-a")

    assert reset.allowed is True
    assert reset.remaining == 0


def test_limiter_keeps_clients_independent():
    clock = FakeClock()
    limiter = FixedWindowRateLimiter(
        limit=1,
        window_seconds=60,
        clock=clock,
    )

    assert limiter.check("client-a").allowed is True
    assert limiter.check("client-a").allowed is False
    assert limiter.check("client-b").allowed is True


def test_memory_limiter_readiness_is_always_available():
    limiter = FixedWindowRateLimiter(
        limit=1,
        window_seconds=60,
    )

    assert limiter.ping() is True


def test_redis_limiter_uses_shared_atomic_counter():
    client = FakeRedis(
        eval_results=[
            [1, 60],
            [2, 59],
        ]
    )
    limiter = RedisFixedWindowRateLimiter(
        limit=1,
        window_seconds=60,
        client=client,
    )

    first = limiter.check("203.0.113.8")
    second = limiter.check("203.0.113.8")

    assert first.allowed is True
    assert first.remaining == 0
    assert second.allowed is False
    assert second.remaining == 0
    assert second.reset_after_seconds == 59


def test_redis_limiter_does_not_put_raw_ip_in_redis_key():
    client = FakeRedis(
        eval_results=[[1, 60]]
    )
    limiter = RedisFixedWindowRateLimiter(
        limit=2,
        window_seconds=60,
        client=client,
    )

    limiter.check("203.0.113.8")

    redis_key = client.eval_calls[0][2]

    assert "203.0.113.8" not in redis_key
    assert redis_key.startswith("llmbastion:rate_limit:")


def test_redis_limiter_readiness_uses_ping():
    client = FakeRedis(
        ping_result=True
    )
    limiter = RedisFixedWindowRateLimiter(
        limit=1,
        window_seconds=60,
        client=client,
    )

    assert limiter.ping() is True


def test_rate_limiter_factory_builds_memory_backend():
    limiter = build_rate_limiter(
        backend="memory",
        limit=2,
        window_seconds=60,
    )

    assert isinstance(
        limiter,
        FixedWindowRateLimiter,
    )


def test_redis_backend_requires_url():
    with pytest.raises(ValueError):
        build_rate_limiter(
            backend="redis",
            limit=2,
            window_seconds=60,
            redis_url=None,
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/chat",
        "/v1/guard",
        "/v1/chat/completions",
    ],
)
def test_chat_middleware_returns_429_and_rate_headers(path):
    app = FastAPI()
    app.add_middleware(
        ChatRateLimitMiddleware,
        limiter=FixedWindowRateLimiter(
            limit=1,
            window_seconds=60,
        ),
    )

    @app.post("/api/v1/chat")
    @app.post("/v1/guard")
    @app.post("/v1/chat/completions")
    def fake_chat():
        return {"ok": True}

    client = TestClient(app)

    first = client.post(path)
    second = client.post(path)

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert first.headers["X-RateLimit-Remaining"] == "0"

    assert second.status_code == 429
    assert second.json() == {
        "detail": "Rate limit exceeded",
        "error": {
            "code": "rate_limit_exceeded",
            "message": "Rate limit exceeded",
        },
    }
    assert second.headers["X-RateLimit-Limit"] == "1"
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert int(second.headers["Retry-After"]) >= 1


def test_chat_middleware_fails_closed_when_backend_is_down():
    class BrokenLimiter:
        def check(self, key):
            raise RuntimeError("redis connection failed")

        def ping(self):
            return False

    app = FastAPI()
    app.add_middleware(
        ChatRateLimitMiddleware,
        limiter=BrokenLimiter(),
    )

    @app.post("/api/v1/chat")
    def fake_chat():
        return {"ok": True}

    client = TestClient(app)
    response = client.post("/api/v1/chat")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == (
        "rate_limiter_unavailable"
    )
    assert "redis connection failed" not in response.text
