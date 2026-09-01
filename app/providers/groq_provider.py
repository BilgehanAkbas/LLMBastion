from .errors import (
    ProviderConfigurationError,
    ProviderResponseError,
)


DEFAULT_MAX_TOKENS = 500
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
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt

    def generate(self, message: str) -> str:
        if not self.api_key:
            raise ProviderConfigurationError(
                "GROQ_API_KEY is not configured"
            )

        from groq import Groq

        client = Groq(api_key=self.api_key)
        completion = client.chat.completions.create(
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

        content = completion.choices[0].message.content
        if content is None or not str(content).strip():
            raise ProviderResponseError(
                "Groq returned an empty response"
            )

        return str(content)
