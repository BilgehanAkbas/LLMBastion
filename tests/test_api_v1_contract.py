import asyncio
from types import SimpleNamespace

import pytest

from app.policies.input_policy import PolicyAction
from app.routers import api_v1


class FakeRuleResult:
    score = 0.0
    matched_rules = ()
    matches = ()


class FakeSemanticResult:
    score = 0.1


class FakeAssessment:
    risk_score = 0.1
    triggered_detectors = ()


class FakeDecision:
    action = PolicyAction.ALLOW


def test_guard_does_not_call_provider(monkeypatch):
    monkeypatch.setattr(
        api_v1.rule_guard,
        "analyze",
        lambda text: FakeRuleResult(),
    )
    monkeypatch.setattr(
        api_v1.semantic_guard,
        "analyze",
        lambda text: FakeSemanticResult(),
    )
    monkeypatch.setattr(
        api_v1.risk_engine,
        "assess",
        lambda **kwargs: FakeAssessment(),
    )
    monkeypatch.setattr(
        api_v1.input_policy,
        "decide_assessment",
        lambda assessment: FakeDecision(),
    )
    monkeypatch.setattr(
        api_v1,
        "save_request_audit",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        api_v1.guard(
            api_v1.GuardRequest(input="Merhaba"),
            db=object(),
        )
    )

    assert result.action == PolicyAction.ALLOW
    assert result.provider_called is False
    assert result.semantic_score == 0.1


def test_chat_completions_maps_allow(monkeypatch):
    async def fake_chat(request, db):
        return SimpleNamespace(
            request_id="abc-123",
            action=PolicyAction.ALLOW,
            risk_score=0.1,
            semantic_score=0.1,
            output_action=None,
            output_findings=(),
            output_redaction_count=0,
            response="Merhaba!",
        )

    monkeypatch.setattr(api_v1, "gateway_chat", fake_chat)

    request = api_v1.ChatCompletionRequest(
        messages=[
            api_v1.CompletionMessage(
                role="user",
                content="Merhaba",
            )
        ]
    )

    result = asyncio.run(
        api_v1.chat_completions(
            request,
            db=object(),
        )
    )

    assert result.object == "chat.completion"
    assert result.model == api_v1.GROQ_MODEL
    assert result.choices[0].message.content == "Merhaba!"
    assert result.choices[0].finish_reason == "stop"
    assert result.llmbastion.action == PolicyAction.ALLOW


def test_chat_completions_maps_block(monkeypatch):
    async def fake_chat(request, db):
        return SimpleNamespace(
            request_id="blocked-1",
            action=PolicyAction.BLOCK,
            risk_score=1.0,
            semantic_score=0.9,
            output_action=None,
            output_findings=(),
            output_redaction_count=0,
            response=None,
        )

    monkeypatch.setattr(api_v1, "gateway_chat", fake_chat)

    request = api_v1.ChatCompletionRequest(
        messages=[
            api_v1.CompletionMessage(
                role="user",
                content="test",
            )
        ]
    )

    result = asyncio.run(
        api_v1.chat_completions(
            request,
            db=object(),
        )
    )

    assert result.choices[0].message.content is None
    assert result.choices[0].finish_reason == "content_filter"
    assert result.llmbastion.action == PolicyAction.BLOCK


def test_chat_completions_rejects_streaming():
    request = api_v1.ChatCompletionRequest(
        messages=[
            api_v1.CompletionMessage(
                role="user",
                content="test",
            )
        ],
        stream=True,
    )

    with pytest.raises(Exception) as exc_info:
        asyncio.run(
            api_v1.chat_completions(
                request,
                db=object(),
            )
        )

    assert getattr(exc_info.value, "status_code", None) == 400


def test_chat_completions_rejects_unconfigured_model(monkeypatch):
    called = False

    async def fake_chat(request, db):
        nonlocal called
        called = True
        raise AssertionError("gateway should not be called")

    monkeypatch.setattr(api_v1, "gateway_chat", fake_chat)

    request = api_v1.ChatCompletionRequest(
        model="different-model",
        messages=[
            api_v1.CompletionMessage(
                role="user",
                content="Merhaba",
            )
        ],
    )

    with pytest.raises(Exception) as exc_info:
        asyncio.run(
            api_v1.chat_completions(
                request,
                db=object(),
            )
        )

    assert getattr(exc_info.value, "status_code", None) == 400
    assert called is False
