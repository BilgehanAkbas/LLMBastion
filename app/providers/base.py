from typing import Protocol


class LLMProvider(Protocol):
    """Minimal interface required by the LLMBastion gateway."""

    async def generate(self, message: str) -> str:
        """Generate a model response for an already-approved user message."""
        ...

    async def close(self) -> None:
        """Release upstream connections after in-flight requests finish."""
        ...
