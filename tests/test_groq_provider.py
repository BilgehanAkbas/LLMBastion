import sys
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.asyncio

from app.providers.errors import (
    ProviderConfigurationError,
    ProviderResponseError,
)
from app.providers.groq_provider import (
    DEFAULT_MAX_TOKENS,
    GroqProvider,
)


class FakeGroq:
    last_create_kwargs = None

    def __init__(self, api_key, *, timeout, max_retries):
        async def create(**kwargs):
            FakeGroq.last_create_kwargs = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="mock response"
                        )
                    )
                ]
            )

        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=create
            )
        )


class EmptyResponseGroq:
    def __init__(self, api_key, *, timeout, max_retries):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=None)
                        )
                    ]
                ))
            )
        )


class WhitespaceResponseGroq:
    def __init__(self, api_key, *, timeout, max_retries):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="   ")
                        )
                    ]
                ))
            )
        )


async def test_groq_provider_returns_text(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(AsyncGroq=FakeGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )

    assert await provider.generate("hello") == "mock response"


async def test_groq_provider_adds_system_prompt_and_length_cap(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(AsyncGroq=FakeGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )
    await provider.generate("Python nedir?")

    kwargs = FakeGroq.last_create_kwargs

    assert kwargs["max_tokens"] == DEFAULT_MAX_TOKENS
    assert kwargs["messages"][0]["role"] == "system"
    assert "concise by default" in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1] == {
        "role": "user",
        "content": "Python nedir?",
    }


async def test_groq_provider_allows_policy_override(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(AsyncGroq=FakeGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
        max_tokens=123,
        system_prompt="custom policy",
    )
    await provider.generate("hello")

    kwargs = FakeGroq.last_create_kwargs

    assert kwargs["max_tokens"] == 123
    assert kwargs["messages"][0] == {
        "role": "system",
        "content": "custom policy",
    }


async def test_groq_provider_requires_api_key():
    provider = GroqProvider(
        api_key=None,
        model="openai/gpt-oss-20b",
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="GROQ_API_KEY is not configured",
    ):
        await provider.generate("hello")


async def test_groq_provider_rejects_empty_response(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(AsyncGroq=EmptyResponseGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )

    with pytest.raises(
        ProviderResponseError,
        match="Groq returned an empty response",
    ):
        await provider.generate("hello")


async def test_groq_provider_rejects_whitespace_response(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(AsyncGroq=WhitespaceResponseGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )

    with pytest.raises(
        ProviderResponseError,
        match="Groq returned an empty response",
    ):
        await provider.generate("hello")
