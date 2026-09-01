from .base import LLMProvider
from .groq_provider import GroqProvider


SUPPORTED_PROVIDERS = ("groq",)


def build_provider(
    provider_name: str,
    *,
    groq_api_key: str | None,
    groq_model: str,
) -> LLMProvider:
    """Build the configured LLM provider behind a common gateway interface."""
    normalized = provider_name.strip().lower()

    if normalized == "groq":
        return GroqProvider(
            api_key=groq_api_key,
            model=groq_model,
        )

    supported = ", ".join(SUPPORTED_PROVIDERS)
    raise ValueError(
        f"Unsupported LLM provider: {provider_name!r}. "
        f"Supported providers: {supported}"
    )
