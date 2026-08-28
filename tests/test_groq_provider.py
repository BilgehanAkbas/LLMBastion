import sys
from types import SimpleNamespace

from app.providers.groq_provider import GroqProvider


class FakeGroq:
    def __init__(self, api_key):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="mock response")
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
