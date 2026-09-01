import pytest

from app.providers.factory import build_provider
from app.providers.groq_provider import GroqProvider


def test_factory_builds_groq_provider():
    provider = build_provider(
        "groq",
        groq_api_key="test-key",
        groq_model="test-model",
    )

    assert isinstance(provider, GroqProvider)
    assert provider.api_key == "test-key"
    assert provider.model == "test-model"


def test_factory_normalizes_provider_name():
    provider = build_provider(
        "  GROQ  ",
        groq_api_key="test-key",
        groq_model="test-model",
    )

    assert isinstance(provider, GroqProvider)


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        build_provider(
            "unknown",
            groq_api_key=None,
            groq_model="test-model",
        )
