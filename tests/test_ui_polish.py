from fastapi.testclient import TestClient
from app.main import create_app

def test_favicon_is_served():
    client = TestClient(create_app("development"))
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")

def test_layout_references_favicon():
    client = TestClient(create_app("development"))
    response = client.get("/")
    assert response.status_code == 200
    assert "/static/favicon.svg" in response.text

def test_development_nav_uses_developer_menu():
    client = TestClient(create_app("development"))
    response = client.get("/")
    assert "Developer" in response.text
    assert "Security Dashboard" in response.text
    assert "API Docs" in response.text

def test_production_nav_hides_developer_menu():
    client = TestClient(create_app("production"))
    response = client.get("/")
    assert response.status_code == 200
    assert "Developer" not in response.text
    assert "Security Dashboard" not in response.text
    assert "API Docs" not in response.text
    assert "GitHub" in response.text
