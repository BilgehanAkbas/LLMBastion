class ProviderError(RuntimeError):
    """Base error for LLM provider failures."""


class ProviderConfigurationError(ProviderError):
    """Raised when the selected provider is not usable due to local config."""


class ProviderResponseError(ProviderError):
    """Raised when the upstream provider returns an unusable response."""
