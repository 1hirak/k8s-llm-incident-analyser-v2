"""Runtime LLM provider configuration, persisted to a JSON file.

llm-svc owns all external LLM API keys. Keys may be configured through
environment variables (the classic path — e.g. OPENAI_API_KEY in
docker-compose) or through the Settings page, which writes them to a
JSON file on a mounted volume. File values take precedence over
environment values so that runtime configuration survives restarts.

API keys are never logged and never returned by any endpoint: the
availability flag is derived from whether a key is present.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Exactly 5 providers — parity: OpenAPI enum, Pydantic ProviderId, TS union
PROVIDER_IDS = ("mock", "openai", "anthropic", "deepseek", "openrouter")

PROVIDER_NAMES = {
    "mock": "Mock (heuristic)",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
}

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "deepseek": "deepseek-chat",
    "mock": "(none)",
    "openrouter": "openrouter/free",
}

FALLBACK_MODEL_OPTIONS = {
    "mock": [{"id": "", "name": "Free mock classifier"}],
    "openai": [
        {"id": "gpt-4o-mini", "name": "GPT-4o mini"},
        {"id": "gpt-4.1-mini", "name": "GPT-4.1 mini"},
        {"id": "gpt-4.1", "name": "GPT-4.1"},
        {"id": "o3-mini", "name": "o3 mini"},
    ],
    "anthropic": [
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5"},
        {"id": "claude-opus-4-1-20250805", "name": "Claude Opus 4.1"},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat"},
        {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner"},
    ],
    "openrouter": [
        {"id": "openrouter/free", "name": "Free (auto-select)"},
        {"id": "openai/gpt-4o-mini", "name": "OpenAI GPT-4o mini"},
        {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "anthropic/claude-3.7-sonnet", "name": "Claude 3.7 Sonnet"},
        {"id": "deepseek/deepseek-chat-v3-0324", "name": "DeepSeek V3"},
    ],
}

_MODEL_CATALOG_TTL = 600
_model_catalog: dict[str, tuple[float, list[dict[str, str]]]] = {}


async def provider_model_options(
    provider: str, api_key: Optional[str]
) -> list[dict[str, str]]:
    """Fetch current provider models, falling back when catalog access fails."""
    cached_at, cached = _model_catalog.get(provider, (0, []))
    if cached and time.monotonic() - cached_at < _MODEL_CATALOG_TTL:
        return cached
    if not api_key and provider != "openrouter":
        return FALLBACK_MODEL_OPTIONS.get(provider, [])

    endpoints = {
        "openai": ("https://api.openai.com/v1/models", "gpt"),
        "anthropic": ("https://api.anthropic.com/v1/models", "claude"),
        "deepseek": ("https://api.deepseek.com/models", "deepseek"),
        "openrouter": ("https://openrouter.ai/api/v1/models", ""),
    }
    endpoint = endpoints.get(provider)
    if endpoint is None:
        return FALLBACK_MODEL_OPTIONS.get(provider, [])
    try:
        url, prefix = endpoint
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if provider == "anthropic":
            headers = {
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01",
            }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            entries = response.json().get("data", [])
        options = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or (
                prefix and not model_id.lower().startswith(prefix)
            ):
                continue
            if provider != "openrouter":
                options.append({"id": model_id, "name": model_id})
                continue
            architecture = entry.get("architecture", {})
            parameters = entry.get("supported_parameters", [])
            if not isinstance(architecture, dict) or not isinstance(parameters, list):
                continue
            modalities = architecture.get("output_modalities", ["text"])
            if "text" not in modalities or not (
                "response_format" in parameters or "structured_outputs" in parameters
            ):
                continue
            options.append({"id": model_id, "name": entry.get("name", model_id)})
        options.sort(key=lambda item: item["name"].lower())
        if options:
            _model_catalog[provider] = (time.monotonic(), options)
            return options
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning(
            "model_catalog_fetch_failed provider=%s error=%s", provider, exc
        )
    return FALLBACK_MODEL_OPTIONS.get(provider, [])

# provider -> environment variable holding its API key
PROVIDER_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

DEFAULT_CONFIG_PATH = "/data/llm-config.json"

# Sentinel: leave the stored model override untouched.
KEEP_MODEL = object()


class LLMConfigStore:
    """JSON-file backed store for the active provider, keys and model."""

    def __init__(self, path: str = DEFAULT_CONFIG_PATH):
        self.path = Path(path)

    # ------------------------------------------------------------------
    # File IO
    # ------------------------------------------------------------------

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "llm_config_read_failed path=%s error=%s", self.path, exc
            )
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".llm-config-"
        )
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Resolution helpers (file first, then environment)
    # ------------------------------------------------------------------

    def _file_provider(self) -> Optional[str]:
        return self._read().get("provider")

    def _file_model(self) -> Optional[str]:
        return self._read().get("model")

    def _file_api_key(self, provider_id: str) -> Optional[str]:
        keys = self._read().get("api_keys") or {}
        key = keys.get(provider_id)
        return key if key else None

    def _env_api_key(self, provider_id: str) -> Optional[str]:
        env_var = PROVIDER_KEY_ENVS.get(provider_id)
        if env_var is None:
            return None
        return os.environ.get(env_var) or None

    def _env_model(self) -> Optional[str]:
        return os.environ.get("LLM_MODEL") or None

    def _env_provider(self) -> str:
        return os.environ.get("LLM_PROVIDER", "mock").lower()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_provider(self) -> tuple[str, Optional[str], Optional[str]]:
        """Resolve the active (provider, model_override, api_key).

        The model override is only the file/env LLM_MODEL value (None if
        the provider default should be used). api_key is None for mock
        and for providers with no configured key.
        """
        provider = self._file_provider() or self._env_provider()
        if provider not in PROVIDER_IDS:
            logger.warning(
                "unknown provider %r — falling back to mock", provider
            )
            provider = "mock"
        model = self._file_model() or self._env_model()
        api_key = self._file_api_key(provider) or self._env_api_key(provider)
        return provider, model, api_key

    def resolve_model(self, provider_id: str) -> str:
        """Model to use for a provider: override or provider default."""
        return (
            self._file_model()
            or self._env_model()
            or DEFAULT_MODELS.get(provider_id, "(none)")
        )

    def is_available(self, provider_id: str) -> bool:
        if provider_id == "mock":
            return True
        return bool(self._file_api_key(provider_id) or self._env_api_key(provider_id))

    def resolve_api_key(self, provider_id: str) -> Optional[str]:
        return self._file_api_key(provider_id) or self._env_api_key(provider_id)

    def get_status(
        self, model_options: Optional[dict[str, list[dict[str, str]]]] = None
    ) -> dict:
        """llm_config_status payload — never contains key values."""
        provider, model, _ = self.resolve_provider()
        return {
            "provider": provider,
            "model": model,
            "source": "file" if self._file_provider() else "env",
            "providers": [
                {
                    "id": pid,
                    "name": PROVIDER_NAMES[pid],
                    "model": self.resolve_model(pid),
                    "available": self.is_available(pid),
                    "models": (model_options or {}).get(
                        pid, FALLBACK_MODEL_OPTIONS.get(pid, [])
                    ),
                }
                for pid in PROVIDER_IDS
            ],
        }

    def set_config(
        self,
        provider: str,
        api_key: Optional[str] = None,
        clear_key: bool = False,
        model=KEEP_MODEL,
    ) -> dict:
        """Persist runtime overrides and return the updated status.

        - api_key present     → store (overwrite) the key for `provider`
        - clear_key           → remove any stored key for `provider`
        - model is a string   → store the model override
        - model is None       → delete the model override (restore default)
        - model is KEEP_MODEL → leave the stored override untouched
        """
        if provider not in PROVIDER_IDS:
            raise ValueError(f"Unknown provider '{provider}'")
        data = self._read()
        if api_key is not None:
            data.setdefault("api_keys", {})[provider] = api_key
        elif clear_key:
            data.setdefault("api_keys", {}).pop(provider, None)
        data["provider"] = provider
        if model is not KEEP_MODEL:
            if model is None:
                data.pop("model", None)
            else:
                data["model"] = model
        self._write(data)
        return self.get_status()
