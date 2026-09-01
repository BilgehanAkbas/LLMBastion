from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_playground_page_loads():
    response = client.get("/playground")

    assert response.status_code == 200
    assert "Security Playground" in response.text
    assert "Message LLMBastion" in response.text
    assert "/static/js/playground.js" in response.text


def test_playground_static_assets_are_served():
    css_response = client.get(
        "/static/css/playground.css"
    )
    js_response = client.get(
        "/static/js/playground.js"
    )

    assert css_response.status_code == 200
    assert js_response.status_code == 200
    assert "playground-shell" in css_response.text
    assert 'fetch("/api/v1/chat"' in js_response.text


def test_playground_loads_markdown_sanitizer():
    response = client.get("/playground")

    assert "marked.min.js" in response.text
    assert "purify.min.js" in response.text

    js_response = client.get(
        "/static/js/playground.js"
    )
    assert "DOMPurify.sanitize" in js_response.text
    assert "marked.parse" in js_response.text
