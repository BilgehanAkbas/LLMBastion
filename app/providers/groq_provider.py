import math

import httpx

from .errors import (
    ProviderConfigurationError,
    ProviderResponseError,
)


DEFAULT_MAX_TOKENS = 500
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 0
DEFAULT_SYSTEM_PROMPT = (
    "You are the response model behind LLMBastion, an LLM security "
    "gateway demo. Answer the user's actual question directly. "
    "Be concise by default: for simple questions, prefer roughly "
    "2-4 short paragraphs or a short bullet list instead of a long "
    "tutorial. Give a longer answer only when the user explicitly "
    "asks for detail, depth, a guide, or a comprehensive explanation. "
    "Do not claim that you accessed email, files, accounts, tools, "
    "or external services unless that capability was actually provided "
    "in the conversation. Markdown is allowed."
)


class GroqProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and greater than 0")
        if type(max_retries) is not int or not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be an integer between 0 and 2")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = None

    def _get_client(self):
        if not self.api_key:
            raise ProviderConfigurationError(
                "GROQ_API_KEY is not configured"
            )

        from groq import AsyncGroq

        # No await during initialization: concurrent tasks on the app loop
        # cannot interleave here. The pooled client belongs to that loop.
        if self._client is None:
            self._client = AsyncGroq(
                api_key=self.api_key,
                timeout=httpx.Timeout(
                    self.timeout_seconds,
                    connect=min(5.0, self.timeout_seconds),
                ),
                max_retries=self.max_retries,
            )
        return self._client

    async def close(self) -> None:
        # Called after the ASGI server has drained requests during shutdown.
        client, self._client = self._client, None
        if client is not None:
            await client.close()

    async def generate(self, message: str) -> str:
        client = self._get_client()
        completion = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.system_prompt,
                },
                {
                    "role": "user",
                    "content": message,
                },
            ],
            max_tokens=self.max_tokens,
        )

        choices = getattr(completion, "choices", None)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise ProviderResponseError("Groq returned a malformed response")

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if content is None:
            raise ProviderResponseError(
                "Groq returned an empty response"
            )
        if not isinstance(content, str):
            raise ProviderResponseError("Groq returned invalid response content")
        if not content.strip():
            raise ProviderResponseError("Groq returned an empty response")

        return content
