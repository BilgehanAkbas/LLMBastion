import io
import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.core.observability import StructuredJsonFormatter
from app.providers.errors import ProviderResponseError
from app.providers.groq_provider import GroqProvider
from app.routers import gateway


def completion(content):
    return NS(choices=[NS(message=NS(content=content))])


CANARY = "synthetic-private-provider-canary"
INVALID_RESPONSES = [
    pytest.param(completion(None), id="null"),
    pytest.param(completion(""), id="empty"),
    pytest.param(completion("   "), id="whitespace"),
    pytest.param(completion(123), id="int"),
    pytest.param(completion(1.5), id="float"),
    pytest.param(completion(True), id="bool"),
    pytest.param(completion({}), id="dict"),
    pytest.param(completion([]), id="list"),
    pytest.param(completion({"text": "hello"}), id="text-object"),
    pytest.param(completion({"secret": CANARY}), id="secret-object"),
    pytest.param(NS(), id="missing-choices"),
    pytest.param(NS(choices=[]), id="empty-choices"),
    pytest.param(NS(choices=None), id="null-choices"),
    pytest.param(NS(choices={0: NS(message=NS(content="hello"))}), id="dict-choices"),
    pytest.param(NS(choices=[NS()]), id="missing-message"),
    pytest.param(NS(choices=[NS(message=None)]), id="null-message"),
    pytest.param(NS(choices=[NS(message=NS())]), id="missing-content"),
    pytest.param(None, id="null-completion"),
]


@pytest.fixture
def structured_logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)


def patch_sdk(monkeypatch, response):
    import groq

    create = AsyncMock(return_value=response)
    constructor = Mock(return_value=NS(chat=NS(completions=NS(create=create))))
    monkeypatch.setattr(groq, "AsyncGroq", constructor)
    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("response", INVALID_RESPONSES)
async def test_adapter_rejects_invalid_response(monkeypatch, response):
    create = patch_sdk(monkeypatch, response)
    adapter = GroqProvider(api_key="synthetic-test-key", model="test-model")
    with pytest.raises(ProviderResponseError) as error:
        await adapter.generate("Synthetic question")
    assert CANARY not in str(error.value)
    assert create.call_count == 1


@pytest.mark.asyncio
async def test_valid_string_is_preserved(monkeypatch):
    text = "  A normal model answer.\n"
    patch_sdk(monkeypatch, completion(text))
    adapter = GroqProvider(api_key="synthetic-test-key", model="test-model")
    assert await adapter.generate("Synthetic question") == text


@pytest.mark.asyncio
@pytest.mark.parametrize("response", INVALID_RESPONSES)
async def test_gateway_rejects_invalid_response_without_output_guard(
    monkeypatch, structured_logs, response,
):
    create = patch_sdk(monkeypatch, response)
    monkeypatch.setattr(gateway, "provider", GroqProvider(api_key="synthetic-test-key", model="test-model"))
    monkeypatch.setattr(gateway.rule_guard, "analyze", lambda text: NS(score=0.0, matches=(), matched_rules=()))
    monkeypatch.setattr(gateway.semantic_guard, "analyze", lambda text: NS(score=0.0))
    output_guard = Mock(side_effect=AssertionError("DataGuard must not run"))
    monkeypatch.setattr(gateway.data_guard, "analyze", output_guard)
    audits = []
    monkeypatch.setattr(gateway, "save_request_audit", lambda db, **fields: audits.append(fields))

    with pytest.raises(HTTPException) as error:
        await gateway.chat(gateway.ChatRequest(message="Synthetic question"), db=None)

    assert error.value.status_code == 502
    assert error.value.detail == "LLM provider returned an invalid response"
    assert create.call_count == 1
    output_guard.assert_not_called()
    assert len(audits) == 1 and audits[0]["action"] == "ERROR"
    provider_result = next(result for result in audits[0]["detector_results"] if result["detector_name"] == "provider")
    assert provider_result["evidence"] == {
        "provider": gateway.LLM_PROVIDER, "status": "ERROR", "error_type": "invalid_response",
    }
    assert CANARY not in json.dumps(audits)
    assert "provider.complete" in structured_logs.getvalue()
    assert CANARY not in structured_logs.getvalue()


@pytest.mark.asyncio
async def test_sdk_exception_secret_does_not_escape(monkeypatch, structured_logs):
    create = patch_sdk(monkeypatch, None)
    create.side_effect = RuntimeError(CANARY)
    monkeypatch.setattr(gateway, "provider", GroqProvider(api_key="synthetic-test-key", model="test-model"))
    monkeypatch.setattr(gateway.rule_guard, "analyze", lambda text: NS(score=0.0, matches=(), matched_rules=()))
    monkeypatch.setattr(gateway.semantic_guard, "analyze", lambda text: NS(score=0.0))
    output_guard = Mock()
    monkeypatch.setattr(gateway.data_guard, "analyze", output_guard)
    audits = []
    monkeypatch.setattr(gateway, "save_request_audit", lambda db, **fields: audits.append(fields))
    with pytest.raises(HTTPException) as error:
        await gateway.chat(gateway.ChatRequest(message="Synthetic question"), db=None)
    assert error.value.status_code == 502
    assert error.value.detail == "LLM provider request failed"
    assert audits[0]["action"] == "ERROR"
    output_guard.assert_not_called()
    assert CANARY not in json.dumps(audits) + str(error.value.detail)
    assert "provider.complete" in structured_logs.getvalue()
    assert CANARY not in structured_logs.getvalue()
