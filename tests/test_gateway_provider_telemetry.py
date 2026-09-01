from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.providers.errors import ProviderConfigurationError
from app.routers import gateway


def _patch_safe_input(monkeypatch):
    monkeypatch.setattr(
        gateway.rule_guard,
        "analyze",
        lambda message: SimpleNamespace(
            score=0.0,
            matches=(),
            matched_rules=(),
        ),
    )
    monkeypatch.setattr(
        gateway.semantic_guard,
        "analyze",
        lambda message: SimpleNamespace(score=0.0),
    )


@pytest.mark.asyncio
async def test_successful_provider_call_is_audited(monkeypatch):
    _patch_safe_input(monkeypatch)

    monkeypatch.setattr(
        gateway.provider,
        "generate",
        lambda message: "safe model response",
    )

    audits = []
    monkeypatch.setattr(
        gateway,
        "save_request_audit",
        lambda db, **kwargs: audits.append(kwargs),
    )

    response = await gateway.chat(
        gateway.ChatRequest(message="hello"),
        db=None,
    )

    assert response.action.value == "ALLOW"
    assert len(audits) == 1

    provider_result = next(
        item
        for item in audits[0]["detector_results"]
        if item["detector_name"] == "provider"
    )
    assert provider_result["score"] == 0.0
    assert provider_result["evidence"] == {
        "provider": gateway.LLM_PROVIDER,
        "status": "SUCCESS",
    }


@pytest.mark.asyncio
async def test_provider_configuration_failure_is_audited(monkeypatch):
    _patch_safe_input(monkeypatch)

    def fail(message):
        raise ProviderConfigurationError(
            "GROQ_API_KEY is not configured"
        )

    monkeypatch.setattr(
        gateway.provider,
        "generate",
        fail,
    )

    audits = []
    monkeypatch.setattr(
        gateway,
        "save_request_audit",
        lambda db, **kwargs: audits.append(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await gateway.chat(
            gateway.ChatRequest(message="hello"),
            db=None,
        )

    assert exc_info.value.status_code == 503
    assert len(audits) == 1
    assert audits[0]["action"] == "ERROR"

    provider_result = next(
        item
        for item in audits[0]["detector_results"]
        if item["detector_name"] == "provider"
    )
    assert provider_result["score"] == 1.0
    assert provider_result["evidence"]["status"] == "ERROR"
    assert (
        provider_result["evidence"]["error_type"]
        == "configuration"
    )


@pytest.mark.asyncio
async def test_unexpected_provider_failure_is_generic_and_audited(
    monkeypatch,
):
    _patch_safe_input(monkeypatch)

    def fail(message):
        raise RuntimeError("upstream internal details")

    monkeypatch.setattr(
        gateway.provider,
        "generate",
        fail,
    )

    audits = []
    monkeypatch.setattr(
        gateway,
        "save_request_audit",
        lambda db, **kwargs: audits.append(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await gateway.chat(
            gateway.ChatRequest(message="hello"),
            db=None,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "LLM provider request failed"
    assert "upstream internal details" not in exc_info.value.detail
    assert audits[0]["action"] == "ERROR"

    provider_result = next(
        item
        for item in audits[0]["detector_results"]
        if item["detector_name"] == "provider"
    )
    assert (
        provider_result["evidence"]["error_type"]
        == "request_failed"
    )
