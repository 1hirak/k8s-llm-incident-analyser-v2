"""Typed exceptions raised by LLM providers.

Each subclass carries an ``status_code`` and an ``error_type`` slug so that
``app.main.analyse_evidence`` can map a provider failure to the appropriate
HTTP response without having to know provider internals.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all LLM failures surfaced to the gateway."""

    status_code: int = 500
    error_type: str = "internal-server-error"

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


class LLMConfigError(LLMError):
    """Configuration problem (missing/invalid API key, unknown provider)."""

    status_code = 500
    error_type = "config-error"


class LLMProviderError(LLMError):
    """Generic upstream provider failure (4xx other than 429)."""

    status_code = 502
    error_type = "upstream-error"


class LLMUnavailableError(LLMProviderError):
    """Provider is unreachable, timed out, or returned 5xx."""

    status_code = 503
    error_type = "provider-unavailable"


class LLMRateLimitError(LLMProviderError):
    """Provider returned 429 / rate limit hit."""

    status_code = 429
    error_type = "rate-limit"


class LLMTruncationError(LLMProviderError):
    """Output was cut off by the token cap (``finish_reason=length``)."""

    status_code = 502
    error_type = "output-truncated"


class LLMContentFilterError(LLMProviderError):
    """Content blocked by the provider's safety system / model refusal."""

    status_code = 502
    error_type = "content-filtered"


class LLMInvalidOutputError(LLMProviderError):
    """Provider response could not be decoded into a JSON object."""

    status_code = 502
    error_type = "invalid-output"


class LLMSchemaError(LLMProviderError):
    """Provider response decoded but did not validate against the schema."""

    status_code = 502
    error_type = "schema-error"
