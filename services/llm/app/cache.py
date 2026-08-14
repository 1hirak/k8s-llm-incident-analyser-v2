"""Fail-open Redis cache for validated incident reports."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Optional

from k8s_llm_shared import EvidencePackage, IncidentReport

from app.prompts import PROMPT_VERSION

try:
    import redis.asyncio as redis
except ImportError:  # pragma: no cover - the service image installs redis
    redis = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
_cache_instances: dict[tuple[str, int], "AnalysisCache"] = {}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def build_cache_key(
    package: EvidencePackage,
    *,
    provider: str,
    model: str,
) -> str:
    """Build a deterministic key from redacted evidence and runtime settings."""
    payload = {
        "package": package.model_dump(mode="json"),
        "provider": provider,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "max_tokens": os.environ.get("LLM_MAX_TOKENS", "4096"),
        "retry_max_tokens": os.environ.get("LLM_RETRY_MAX_TOKENS", "8192"),
        "reasoning_effort": os.environ.get("OPENROUTER_REASONING_EFFORT", ""),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return f"llm:analysis:v{SCHEMA_VERSION}:{digest}"


class AnalysisCache:
    def __init__(self, url: str = "", ttl_seconds: int = 900, client: Any = None):
        self.url = url
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._disabled = client is None and not url
        self._warned = False

    @property
    def enabled(self) -> bool:
        return not self._disabled

    async def _get_client(self) -> Any:
        if self._disabled:
            return None
        if self._client is not None:
            return self._client
        if redis is None:
            self._disabled = True
            return None
        try:
            self._client = redis.from_url(self.url, decode_responses=True)
            await self._client.ping()
            return self._client
        except Exception as exc:  # cache failures must never fail analysis
            self._disabled = True
            self._warn_unavailable(exc)
            return None

    def _warn_unavailable(self, exc: Exception) -> None:
        if not self._warned:
            logger.warning("analysis_cache_unavailable error=%s", exc)
            self._warned = True

    async def get(self, key: str) -> Optional[IncidentReport]:
        client = await self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            return IncidentReport.model_validate(json.loads(raw))
        except Exception as exc:
            self._warn_unavailable(exc)
            try:
                await client.delete(key)
            except Exception:
                pass
            return None

    async def set(self, key: str, report: IncidentReport) -> None:
        client = await self._get_client()
        if client is None:
            return
        # IDs and timestamps belong to the current analysis job, not the cache.
        payload = report.model_dump(
            mode="json", exclude={"incident_id", "created_at"}
        )
        try:
            await client.set(key, json.dumps(payload), ex=self.ttl_seconds)
        except Exception as exc:
            self._warn_unavailable(exc)


def get_analysis_cache() -> AnalysisCache:
    """Return a process-local cache client configured from the environment."""
    enabled = os.environ.get("LLM_ANALYSIS_CACHE_ENABLED", "true").lower()
    url = os.environ.get("REDIS_URL", "") if enabled not in {"0", "false", "no"} else ""
    ttl = _env_int("LLM_ANALYSIS_CACHE_TTL", 900)
    cache_id = (url, ttl)
    if cache_id not in _cache_instances:
        _cache_instances[cache_id] = AnalysisCache(url, ttl)
    return _cache_instances[cache_id]
