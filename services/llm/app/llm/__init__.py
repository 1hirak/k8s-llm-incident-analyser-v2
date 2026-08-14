"""LLM provider registry.

Providers are imported eagerly at module load: a request-time import
failure must never surface as a 500 mid-analysis. Provider *selection*
still happens per-call via the runtime config store, which resolves
the active provider, model and API key from the config file first and
the environment second (API keys are only read when the provider is
instantiated, so unused providers need no configuration).
"""

import logging
import os

from app.config_store import DEFAULT_CONFIG_PATH, LLMConfigStore
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import BaseLLMProvider
from app.llm.deepseek_provider import DeepSeekProvider
from app.llm.mock_provider import MockProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
    "openrouter": OpenRouterProvider,
}


def get_provider(store: LLMConfigStore | None = None) -> BaseLLMProvider:
    store = store or LLMConfigStore(
        os.environ.get("LLM_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    )
    provider, model, api_key = store.resolve_provider()
    provider_class = _PROVIDERS.get(provider, MockProvider)
    if provider_class is MockProvider or provider == "mock":
        return provider_class()
    return provider_class(api_key=api_key, model=model)
