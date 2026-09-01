from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main


def test_legacy_favicon_path_no_longer_returns_404():
    client = TestClient(
        main.create_app("development")
    )

    response = client.get(
        "/favicon.ico",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/static/favicon.svg"


def test_development_security_headers_are_present():
    client = TestClient(
        main.create_app("development")
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers[
        "Content-Security-Policy"
    ]
    assert "Strict-Transport-Security" not in response.headers


def test_production_security_headers_are_stricter():
    client = TestClient(
        main.create_app("production")
    )

    response = client.get("/health")

    csp = response.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1]
    assert response.headers["Strict-Transport-Security"].startswith(
        "max-age=31536000"
    )


def test_chat_request_body_limit_returns_structured_413():
    client = TestClient(
        main.create_app(
            "development",
            max_request_body_bytes=64,
        )
    )

    response = client.post(
        "/api/v1/chat",
        content=b"x" * 128,
        headers={
            "Content-Type": "application/json",
        },
    )

    payload = response.json()

    assert response.status_code == 413
    assert payload["detail"] == "Request body is too large"
    assert payload["error"]["code"] == "request_too_large"
    assert payload["error"]["details"]["max_bytes"] == 64
    assert response.headers["Cache-Control"] == "no-store"


def test_validation_errors_use_structured_format():
    client = TestClient(
        main.create_app("development")
    )

    response = client.post(
        "/api/v1/chat",
        json={},
    )

    payload = response.json()

    assert response.status_code == 422
    assert payload["detail"] == "Request validation failed"
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"]
    assert "input" not in payload["error"]["details"][0]


def test_404_uses_structured_format():
    client = TestClient(
        main.create_app("development")
    )

    response = client.get("/does-not-exist")
    payload = response.json()

    assert response.status_code == 404
    assert payload["error"]["code"] == "not_found"
    assert payload["error"]["message"] == "Not Found"


def test_development_5xx_http_detail_is_visible():
    application = main.create_app("development")

    @application.get("/_test-service-error")
    def test_service_error():
        raise HTTPException(
            status_code=503,
            detail="development diagnostic",
        )

    client = TestClient(application)
    response = client.get("/_test-service-error")

    assert response.status_code == 503
    assert response.json()["detail"] == "development diagnostic"


def test_production_5xx_http_detail_is_generic():
    application = main.create_app("production")

    @application.get("/_test-service-error")
    def test_service_error():
        raise HTTPException(
            status_code=503,
            detail="secret provider configuration detail",
        )

    client = TestClient(application)
    response = client.get("/_test-service-error")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Service temporarily unavailable"
    )
    assert "secret provider" not in response.text


def test_ready_returns_200_when_local_checks_pass(
    monkeypatch,
):
    monkeypatch.setattr(
        main,
        "_check_database_ready",
        lambda: None,
    )
    monkeypatch.setattr(
        main.semantic_guard,
        "ensure_ready",
        lambda: None,
    )
    monkeypatch.setattr(
        main,
        "_check_provider_configuration",
        lambda: None,
    )

    client = TestClient(
        main.create_app("development")
    )
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {
        "database": "ok",
        "semantic_guard": "ok",
        "provider_config": "ok",
    }


def test_ready_returns_structured_503_when_a_check_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        main,
        "_check_database_ready",
        lambda: None,
    )
    monkeypatch.setattr(
        main.semantic_guard,
        "ensure_ready",
        lambda: None,
    )

    def fail_provider():
        raise RuntimeError("provider config missing")

    monkeypatch.setattr(
        main,
        "_check_provider_configuration",
        fail_provider,
    )

    client = TestClient(
        main.create_app("production")
    )
    response = client.get("/ready")
    payload = response.json()

    assert response.status_code == 503
    assert payload["error"]["code"] == "service_unavailable"
    assert payload["detail"] == "Service temporarily unavailable"
    assert "provider config missing" not in response.text
