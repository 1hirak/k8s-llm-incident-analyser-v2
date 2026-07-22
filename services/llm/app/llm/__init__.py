"""LLM provider registry.

Providers are imported eagerly at module load: a request-time import
failure must never surface as a 500 mid-analysis. Provider *selection*
still happens per-call via the LLM_PROVIDER env var (API keys are only
read when the provider is instantiated, so unused providers need no
configuration).
"""

import logging
import os

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import BaseLLMProvider
from app.llm.deepseek_provider import DeepSeekProvider
from app.llm.mock_provider import MockProvider
from app.llm.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
}


def get_provider() -> BaseLLMProvider:
    provider = os.environ.get("LLM_PROVIDER", "mock").lower()
    provider_class = _PROVIDERS.get(provider)
    if provider_class is None:
        logger.warning(
            "Unknown LLM_PROVIDER='%s' — falling back to mock", provider
        )
        provider_class = MockProvider
    return provider_class()
