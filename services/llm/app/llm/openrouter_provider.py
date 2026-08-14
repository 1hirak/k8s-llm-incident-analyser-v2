import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Optional

import httpx
from k8s_llm_shared import EvidencePackage, IncidentReport
from pydantic import ValidationError

from app.llm.base import BaseLLMProvider
from app.llm.errors import (
    LLMConfigError,
    LLMContentFilterError,
    LLMInvalidOutputError,
    LLMRateLimitError,
    LLMSchemaError,
    LLMTruncationError,
    LLMUnavailableError,
)
from app.prompts import build_prompt

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_RETRY_MAX_TOKENS = 8192
_MAX_ATTEMPTS = 2
_JSON_INSTRUCTION = "\n\nRespond with valid JSON conforming to this schema:\n{schema}"


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("invalid_integer_config name=%s default=%s", name, default)
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def _response_content(message: dict[str, Any]) -> str:
    """Return text from both legacy and content-block chat responses."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ).strip()
    return ""


def _parse_json_content(content: str) -> Any:
    """Parse JSON returned directly or inside a Markdown code fence."""
    if not content:
        raise json.JSONDecodeError("empty response", content, 0)
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        content = "\n".join(lines[1:-1]).strip()
        if content.lower().startswith("json\n"):
            content = content[5:]
    return json.loads(content)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    detail: Optional[str] = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            raw = err.get("message")
            if isinstance(raw, str):
                detail = raw
    if not detail:
        detail = response.text[:300] or response.reason_phrase
    if status in (401, 403):
        raise LLMConfigError(f"OpenRouter authentication failed ({status}): {detail}")
    if status == 429:
        raise LLMRateLimitError(f"OpenRouter rate limit hit: {detail}")
    if 500 <= status < 600:
        raise LLMUnavailableError(f"OpenRouter returned {status}: {detail}")
    raise LLMConfigError(f"OpenRouter rejected the request ({status}): {detail}")


def _session_id(package: EvidencePackage) -> str:
    encoded = json.dumps(
        package.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return f"k8s-incident-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _retry_delay(attempt: int) -> float:
    base = _env_float("OPENROUTER_RETRY_DELAY_SECONDS", 2.0)
    return min(30.0, base * (2**attempt))


def _usage_log(data: dict[str, Any], response: httpx.Response, attempt: int) -> None:
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    prompt_details = usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = usage.get("completion_tokens_details")
    completion_details = (
        completion_details if isinstance(completion_details, dict) else {}
    )
    headers = getattr(response, "headers", {}) or {}
    choices = data.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    finish_reason = (
        first_choice.get("finish_reason") if isinstance(first_choice, dict) else None
    )
    logger.info(
        "openrouter_usage model=%s attempt=%s finish_reason=%s "
        "prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s "
        "cached_tokens=%s cache_write_tokens=%s response_cache_status=%s",
        data.get("model"),
        attempt,
        finish_reason,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        completion_details.get("reasoning_tokens"),
        prompt_details.get("cached_tokens"),
        prompt_details.get("cache_write_tokens"),
        headers.get("X-OpenRouter-Cache-Status"),
    )


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter chat completions with bounded retries and cache affinity."""

    def __init__(
        self, api_key: Optional[str] = None, model: Optional[str] = None
    ):
        api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMConfigError(
                "Missing API key: set OPENROUTER_API_KEY or configure the provider."
            )
        self.api_key = api_key
        self.model = model or os.environ.get("LLM_MODEL", "openrouter/free")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def _request_payload(
        self,
        package: EvidencePackage,
        system_msg: str,
        user_msg: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        schema_instruction = _JSON_INSTRUCTION.format(
            schema=json.dumps(IncidentReport.model_json_schema(), separators=(",", ":"))
        )
        if _enabled("OPENROUTER_PROMPT_CACHE", True):
            system_content: str | list[dict[str, Any]] = [
                {"type": "text", "text": system_msg},
                {
                    "type": "text",
                    "text": schema_instruction,
                    "cache_control": {"type": "ephemeral"},
                },
            ]
        else:
            system_content = system_msg + schema_instruction

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_msg},
            ],
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "provider": {"require_parameters": True},
            "session_id": _session_id(package),
        }
        reasoning_effort = os.environ.get("OPENROUTER_REASONING_EFFORT", "").strip()
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        return payload

    def _headers(self, *, clear_cache: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", ""),
            "X-Title": os.environ.get("OPENROUTER_APP_NAME", "K8s Incident Analyser"),
        }
        if _enabled("OPENROUTER_RESPONSE_CACHE", False):
            headers["X-OpenRouter-Cache"] = "true"
            if clear_cache:
                headers["X-OpenRouter-Cache-Clear"] = "true"
        return headers

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        system_msg, user_msg = build_prompt(package)
        max_tokens = _env_int("LLM_MAX_TOKENS", _DEFAULT_MAX_TOKENS)
        retry_max_tokens = max(
            max_tokens, _env_int("LLM_RETRY_MAX_TOKENS", _DEFAULT_RETRY_MAX_TOKENS)
        )
        logger.info(
            "Calling OpenRouter model=%s max_tokens=%s retry_max_tokens=%s",
            self.model,
            max_tokens,
            retry_max_tokens,
        )

        async with httpx.AsyncClient() as client:
            clear_cache = False
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    response = await client.post(
                        self.base_url,
                        headers=self._headers(clear_cache=clear_cache),
                        json=self._request_payload(
                            package, system_msg, user_msg, max_tokens
                        ),
                        timeout=60,
                    )
                    _raise_for_status(response)
                except httpx.TimeoutException as exc:
                    if attempt == 0:
                        await asyncio.sleep(_retry_delay(attempt))
                        continue
                    raise LLMUnavailableError(
                        f"OpenRouter request timed out: {exc}"
                    ) from exc
                except httpx.HTTPError as exc:
                    if attempt == 0:
                        await asyncio.sleep(_retry_delay(attempt))
                        continue
                    raise LLMUnavailableError(
                        f"OpenRouter connection error: {exc}"
                    ) from exc
                except (LLMRateLimitError, LLMUnavailableError):
                    if attempt == 0:
                        await asyncio.sleep(_retry_delay(attempt))
                        continue
                    raise

                try:
                    data = response.json()
                except ValueError as exc:
                    raise LLMInvalidOutputError(
                        "OpenRouter returned a non-JSON HTTP response"
                    ) from exc
                if not isinstance(data, dict):
                    raise LLMInvalidOutputError("OpenRouter response is not an object")

                _usage_log(data, response, attempt + 1)
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise LLMInvalidOutputError(
                        "OpenRouter response is missing `choices`"
                    )
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise LLMInvalidOutputError(
                        "OpenRouter `choices[0]` is not an object"
                    )
                message = choice.get("message")
                if not isinstance(message, dict):
                    raise LLMInvalidOutputError(
                        "OpenRouter `choices[0].message` is not an object"
                    )

                finish_reason = choice.get("finish_reason")
                finish_reason = (
                    finish_reason if isinstance(finish_reason, str) else None
                )
                refusal = message.get("refusal")
                if refusal:
                    raise LLMContentFilterError(
                        f"OpenRouter refusal: {refusal!r} (finish_reason={finish_reason})"
                    )

                content = _response_content(message)
                if finish_reason == "length":
                    if attempt == 0 and max_tokens < retry_max_tokens:
                        max_tokens = retry_max_tokens
                        clear_cache = True
                        logger.warning(
                            "OpenRouter output truncated; retrying with max_tokens=%s",
                            max_tokens,
                        )
                        continue
                    if not content:
                        raise LLMTruncationError(
                            "OpenRouter returned no content (finish_reason=length)"
                        )
                    raise LLMTruncationError(
                        "OpenRouter returned truncated JSON (finish_reason=length)"
                    )
                if not content:
                    raise LLMInvalidOutputError(
                        f"OpenRouter returned empty content (finish_reason={finish_reason})"
                    )

                try:
                    raw_json = _parse_json_content(content)
                except json.JSONDecodeError as exc:
                    raise LLMInvalidOutputError(
                        f"OpenRouter returned non-JSON output (finish_reason={finish_reason}): {exc}"
                    ) from exc

                try:
                    return IncidentReport.model_validate(raw_json)
                except ValidationError as exc:
                    raise LLMSchemaError(
                        f"OpenRouter output did not match schema: {exc}"
                    ) from exc

        raise LLMUnavailableError("OpenRouter analysis did not return a result")
