from typing import Protocol


class LLMProvider(Protocol):
    """Minimal interface required by the LLMBastion gateway."""

    def generate(self, message: str) -> str:
        """Generate a model response for an already-approved user message."""
        ...
