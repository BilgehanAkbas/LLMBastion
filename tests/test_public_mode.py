from fastapi.testclient import TestClient

from app.main import create_app


def route_paths(application):
    return {
        route.path
        for route in application.routes
        if hasattr(route, "path")
    }


def test_landing_page_is_root_in_development():
    application = create_app("development")
    client = TestClient(application)

    response = client.get("/")

    assert response.status_code == 200
    assert "Put a security layer" in response.text
    assert 'href="/playground"' in response.text


def test_development_registers_internal_tools():
    application = create_app("development")
    paths = route_paths(application)

    assert "/dashboard" in paths
    assert "/docs" in paths
    assert "/openapi.json" in paths


def test_development_nav_shows_internal_tools():
    application = create_app("development")
    client = TestClient(application)

    response = client.get("/playground")

    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "API Docs" in response.text


def test_production_does_not_register_internal_tools():
    application = create_app("production")
    paths = route_paths(application)

    assert "/dashboard" not in paths
    assert "/docs" not in paths
    assert "/openapi.json" not in paths


def test_production_internal_urls_return_404():
    application = create_app("production")
    client = TestClient(application)

    assert client.get("/dashboard").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_production_keeps_public_product_routes():
    application = create_app("production")
    client = TestClient(application)

    assert client.get("/").status_code == 200
    assert client.get("/playground").status_code == 200
    assert client.get("/health").status_code == 200

    response = client.get("/playground")
    assert "Dashboard" not in response.text
    assert "API Docs" not in response.text
    assert "View Source on GitHub" in response.text
