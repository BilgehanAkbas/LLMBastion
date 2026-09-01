import sys
from types import SimpleNamespace

import pytest

from app.providers.errors import (
    ProviderConfigurationError,
    ProviderResponseError,
)
from app.providers.groq_provider import GroqProvider


class FakeGroq:
    def __init__(self, api_key):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="mock response"
                            )
                        )
                    ]
                )
            )
        )


class EmptyResponseGroq:
    def __init__(self, api_key):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=None)
                        )
                    ]
                )
            )
        )


class WhitespaceResponseGroq:
    def __init__(self, api_key):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="   ")
                        )
                    ]
                )
            )
        )


def test_groq_provider_returns_text(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(Groq=FakeGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )

    assert provider.generate("hello") == "mock response"


def test_groq_provider_requires_api_key():
    provider = GroqProvider(
        api_key=None,
        model="openai/gpt-oss-20b",
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="GROQ_API_KEY is not configured",
    ):
        provider.generate("hello")


def test_groq_provider_rejects_empty_response(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(Groq=EmptyResponseGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )

    with pytest.raises(
        ProviderResponseError,
        match="Groq returned an empty response",
    ):
        provider.generate("hello")


def test_groq_provider_rejects_whitespace_response(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "groq",
        SimpleNamespace(Groq=WhitespaceResponseGroq),
    )

    provider = GroqProvider(
        api_key="test-key",
        model="openai/gpt-oss-20b",
    )

    with pytest.raises(
        ProviderResponseError,
        match="Groq returned an empty response",
    ):
        provider.generate("hello")
