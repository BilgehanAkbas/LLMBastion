from .base import LLMProvider
from .groq_provider import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_SECONDS, GroqProvider


SUPPORTED_PROVIDERS = ("groq",)


def build_provider(
    provider_name: str,
    *,
    groq_api_key: str | None,
    groq_model: str,
    groq_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    groq_max_retries: int = DEFAULT_MAX_RETRIES,
) -> LLMProvider:
    """Build the configured LLM provider behind a common gateway interface."""
    normalized = provider_name.strip().lower()

    if normalized == "groq":
        return GroqProvider(
            api_key=groq_api_key,
            model=groq_model,
            timeout_seconds=groq_timeout_seconds,
            max_retries=groq_max_retries,
        )

    supported = ", ".join(SUPPORTED_PROVIDERS)
    raise ValueError(
        f"Unsupported LLM provider: {provider_name!r}. "
        f"Supported providers: {supported}"
    )
