import io
import json
import logging
from pathlib import Path
import runpy
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import groq
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.observability import StructuredJsonFormatter
from app.providers.factory import build_provider
from app.providers.groq_provider import GroqProvider
from app.routers import gateway

CANARY = "synthetic-upstream-private-detail"


def config_values(monkeypatch):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///synthetic.db")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "app/core/config.py"))


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("GROQ_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("GROQ_MAX_RETRIES", raising=False)
    values = config_values(monkeypatch)
    assert values["GROQ_TIMEOUT_SECONDS"] == 20
    assert values["GROQ_MAX_RETRIES"] == 0


@pytest.mark.asyncio
async def test_config_overrides_reach_sdk(monkeypatch):
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "3.25")
    monkeypatch.setenv("GROQ_MAX_RETRIES", "1")
    values = config_values(monkeypatch)
    sdk = Mock()
    sdk.close = AsyncMock()
    sdk.chat.completions.create = AsyncMock()
    sdk.chat.completions.create.return_value = NS(choices=[NS(message=NS(content="Synthetic answer"))])
    constructor = Mock(return_value=sdk)
    monkeypatch.setattr(groq, "AsyncGroq", constructor)
    provider = build_provider("groq", groq_api_key="synthetic-key", groq_model="synthetic-model",
                              groq_timeout_seconds=values["GROQ_TIMEOUT_SECONDS"],
                              groq_max_retries=values["GROQ_MAX_RETRIES"])
    assert await provider.generate("Synthetic question") == "Synthetic answer"
    options = constructor.call_args.kwargs
    assert options["timeout"].as_dict() == {"connect": 3.25, "read": 3.25, "write": 3.25, "pool": 3.25}
    assert options["max_retries"] == 1
    await provider.close()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "bad"])
def test_invalid_timeout_config_rejected(monkeypatch, value):
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", value)
    monkeypatch.setenv("GROQ_MAX_RETRIES", "0")
    with pytest.raises(ValueError):
        config_values(monkeypatch)


@pytest.mark.parametrize("value", ["-1", "3", "1.5", "bad"])
def test_invalid_retry_config_rejected(monkeypatch, value):
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("GROQ_MAX_RETRIES", value)
    with pytest.raises(ValueError):
        config_values(monkeypatch)


@pytest.mark.asyncio
async def test_client_reused_concurrently_and_closed(monkeypatch):
    sdk = Mock()
    sdk.close = AsyncMock()
    sdk.chat.completions.create = AsyncMock()
    sdk.chat.completions.create.return_value = NS(choices=[NS(message=NS(content="Synthetic answer"))])
    constructor = Mock(return_value=sdk)
    monkeypatch.setattr(groq, "AsyncGroq", constructor)
    provider = GroqProvider(api_key="synthetic-key", model="synthetic-model")
    answers = await asyncio.gather(*(provider.generate("Synthetic question") for _ in range(16)))
    assert answers == ["Synthetic answer"] * 16
    assert constructor.call_count == 1
    assert sdk.chat.completions.create.call_count == 16
    options = constructor.call_args.kwargs
    assert options["timeout"].as_dict() == {"connect": 5.0, "read": 20.0, "write": 20.0, "pool": 20.0}
    assert options["max_retries"] == 0
    await provider.close()
    await provider.close()
    sdk.close.assert_called_once()


def test_application_shutdown_closes_provider(monkeypatch):
    import app.main as main

    close = AsyncMock()
    monkeypatch.setattr(main.gateway_provider, "close", close)
    with TestClient(main.create_app()):
        close.assert_not_called()
    close.assert_called_once()


def synthetic_http(monkeypatch, scenario):
    calls = Mock()
    def handle(request):
        calls(request.extensions["timeout"])
        if scenario == "timeout":
            raise httpx.ReadTimeout(CANARY, request=request)
        if scenario in (429, 500):
            return httpx.Response(scenario, json={"error": {"message": CANARY}}, headers={"retry-after": "0.02"})
        return httpx.Response(200, json={
            "id": "synthetic", "object": "chat.completion", "created": 0, "model": "synthetic-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": None if scenario == "invalid" else "Synthetic answer"}, "finish_reason": "stop"}],
        })
    real_constructor = groq.AsyncGroq
    clients = []
    def construct(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        clients.append(client)
        return real_constructor(**kwargs, http_client=client)
    monkeypatch.setattr(groq, "AsyncGroq", construct)
    return calls, clients


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["timeout", 429, 500])
@pytest.mark.parametrize("retries", [0, 1, 2])
async def test_sdk_attempt_count_matches_retry_policy(monkeypatch, scenario, retries):
    calls, clients = synthetic_http(monkeypatch, scenario)
    sleep = AsyncMock()
    monkeypatch.setattr(groq._base_client.AsyncAPIClient, "_sleep_for_retry", sleep)
    provider = GroqProvider(api_key="synthetic-key", model="synthetic-model", timeout_seconds=0.25, max_retries=retries)
    try:
        with pytest.raises(groq.GroqError):
            await provider.generate("Synthetic question")
        assert calls.call_count == retries + 1
        assert sleep.call_count == retries
        assert all(call.args[0]["read"] == 0.25 for call in calls.call_args_list)
    finally:
        await provider.close()
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["timeout", 429, 500, "invalid"])
async def test_failure_is_safe_and_audited(monkeypatch, scenario):
    calls, _ = synthetic_http(monkeypatch, scenario)
    provider = GroqProvider(api_key="synthetic-key", model="synthetic-model")
    monkeypatch.setattr(gateway, "provider", provider)
    monkeypatch.setattr(gateway.rule_guard, "analyze", lambda message: NS(score=0, matches=(), matched_rules=()))
    monkeypatch.setattr(gateway.semantic_guard, "analyze", lambda message: NS(score=0))
    audits = []
    monkeypatch.setattr(gateway, "save_request_audit", lambda db, **fields: audits.append(fields))
    output_guard = Mock(side_effect=AssertionError("DataGuard must not run"))
    monkeypatch.setattr(gateway.data_guard, "analyze", output_guard)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        with pytest.raises(HTTPException) as error:
            await gateway.chat(gateway.ChatRequest(message="Synthetic question"), db=None)
        assert error.value.status_code == 502
        assert error.value.detail in {"LLM provider request failed", "LLM provider returned an invalid response"}
        assert calls.call_count == 1
        assert audits[0]["action"] == "ERROR"
        output_guard.assert_not_called()
        assert "provider.complete" in stream.getvalue()
        assert CANARY not in str(error.value.detail) + json.dumps(audits) + stream.getvalue()
    finally:
        logger.removeHandler(handler)
        await provider.close()


@pytest.mark.asyncio
async def test_block_never_initializes_client_or_sends_request(monkeypatch):
    constructor = Mock(side_effect=AssertionError("SDK must not initialize"))
    monkeypatch.setattr(groq, "AsyncGroq", constructor)
    monkeypatch.setattr(gateway, "provider", GroqProvider(api_key="synthetic-key", model="synthetic-model"))
    monkeypatch.setattr(gateway.rule_guard, "analyze", lambda message: NS(score=1, matches=(), matched_rules=()))
    monkeypatch.setattr(gateway.semantic_guard, "analyze", lambda message: NS(score=0))
    monkeypatch.setattr(gateway, "save_request_audit", lambda *args, **kwargs: None)
    output_guard = Mock()
    monkeypatch.setattr(gateway.data_guard, "analyze", output_guard)
    result = await gateway.chat(gateway.ChatRequest(message="Synthetic blocked question"), db=None)
    assert result.action.value == "BLOCK"
    assert result.response is None
    constructor.assert_not_called()
    output_guard.assert_not_called()
