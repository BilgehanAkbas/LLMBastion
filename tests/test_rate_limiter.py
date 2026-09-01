from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.rate_limiter import (
    ChatRateLimitMiddleware,
    FixedWindowRateLimiter,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


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


def test_chat_middleware_returns_429_and_rate_headers():
    app = FastAPI()
    app.add_middleware(
        ChatRateLimitMiddleware,
        limiter=FixedWindowRateLimiter(
            limit=1,
            window_seconds=60,
        ),
    )

    @app.post("/api/v1/chat")
    def fake_chat():
        return {"ok": True}

    client = TestClient(app)

    first = client.post("/api/v1/chat")
    second = client.post("/api/v1/chat")

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
