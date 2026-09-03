import io
import json
import logging
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.observability import (
    StructuredJsonFormatter,
    bind_request_id,
    get_request_id,
    log_event,
    reset_request_id,
)
from app.services.request_context import RequestContextMiddleware


def _capture_logger(name: str):
    stream = io.StringIO()
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(handler)
    return logger, stream


def _last_payload(stream: io.StringIO) -> dict:
    lines = [
        line
        for line in stream.getvalue().splitlines()
        if line.strip()
    ]
    return json.loads(lines[-1])


def test_structured_json_log_contains_operational_fields():
    logger, stream = _capture_logger("test.observability.basic")
    token = bind_request_id(
        "11111111-1111-4111-8111-111111111111"
    )
    try:
        log_event(
            logger,
            logging.INFO,
            "provider.complete",
            provider="groq",
            provider_status="success",
            latency_ms=12.5,
        )
    finally:
        reset_request_id(token)

    payload = _last_payload(stream)

    assert payload["service"] == "LLMBastion"
    assert payload["level"] == "INFO"
    assert payload["event"] == "provider.complete"
    assert payload["request_id"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert payload["provider"] == "groq"
    assert payload["provider_status"] == "success"
    assert payload["latency_ms"] == 12.5
    assert payload["timestamp"].endswith("Z")


def test_structured_logger_drops_prompt_response_and_secret_fields():
    logger, stream = _capture_logger("test.observability.privacy")
    secret = "sk-super-secret-value"

    log_event(
        logger,
        logging.INFO,
        "provider.complete",
        provider="groq",
        prompt=secret,
        response=secret,
        api_key=secret,
        raw_evidence=secret,
    )

    output = stream.getvalue()
    payload = _last_payload(stream)

    assert secret not in output
    assert "prompt" not in payload
    assert "response" not in payload
    assert "api_key" not in payload
    assert "raw_evidence" not in payload


def test_exception_message_and_traceback_text_are_not_serialized():
    logger, stream = _capture_logger("test.observability.exception")
    secret = "user@example.com"

    try:
        raise RuntimeError(f"provider failed with {secret}")
    except RuntimeError as exc:
        log_event(
            logger,
            logging.ERROR,
            "provider.complete",
            provider="groq",
            provider_status="error",
            error_type="request_failed",
            exc_info=(
                type(exc),
                exc,
                exc.__traceback__,
            ),
        )

    output = stream.getvalue()
    payload = _last_payload(stream)

    assert secret not in output
    assert "provider failed" not in output
    assert payload["exception_type"] == "RuntimeError"


def test_dynamic_unsafe_event_name_is_replaced():
    logger, stream = _capture_logger("test.observability.event")

    log_event(
        logger,
        logging.INFO,
        "user@example.com says secret",
    )

    payload = _last_payload(stream)

    assert payload["event"] == "application.log"
    assert "user@example.com" not in stream.getvalue()


def _make_context_app():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/context")
    def context():
        return {"request_id": get_request_id()}

    @app.get("/items/{item_id}")
    def item(item_id: str, request: Request):
        return {"ok": True}

    return app


def test_request_context_header_matches_bound_context_id():
    client = TestClient(_make_context_app())

    response = client.get("/context")
    request_id = response.headers["X-Request-ID"]

    UUID(request_id)
    assert response.json()["request_id"] == request_id


def test_request_context_uses_server_owned_id_not_client_header():
    client = TestClient(_make_context_app())
    attacker_value = "attacker-controlled-request-id"

    response = client.get(
        "/context",
        headers={"X-Request-ID": attacker_value},
    )

    assert response.headers["X-Request-ID"] != attacker_value
    assert response.json()["request_id"] == response.headers[
        "X-Request-ID"
    ]


def test_request_logs_use_route_template_not_sensitive_path_value():
    logger = logging.getLogger("app.services.request_context")
    previous_handlers = list(logger.handlers)
    previous_propagate = logger.propagate
    previous_level = logger.level

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    secret_path_value = "sk-path-secret-123"
    try:
        client = TestClient(_make_context_app())
        response = client.get(f"/items/{secret_path_value}")
        assert response.status_code == 200
    finally:
        logger.handlers = previous_handlers
        logger.propagate = previous_propagate
        logger.setLevel(previous_level)

    payload = _last_payload(stream)

    assert secret_path_value not in stream.getvalue()
    assert payload["path"] == "/items/{item_id}"
    assert payload["event"] == "http.request_complete"
