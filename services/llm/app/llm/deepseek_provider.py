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
    LLMInvalidOutputError,
    LLMRateLimitError,
    LLMSchemaError,
    LLMTruncationError,
    LLMUnavailableError,
)
from app.prompts import build_prompt

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_RETRY_MAX_TOKENS = 4096

_JSON_INSTRUCTION_TEMPLATE = (
    "\n\nYou MUST respond with valid JSON (json_object) conforming to "
    "this schema:\n{schema}\n\n"
    'Example: {{"incident_id": "inc-001", "severity": "high", '
    '"failure_category": "crash", "likely_root_cause": "...", '
    '"suggested_fix": "...", "confidence": 0.8, '
    '"supporting_evidence": [{{"source": "logs", "pod": "demo-app", '
    '"evidence": "..."}}], "recommended_commands": ["kubectl ..."], '
    '"human_verification_steps": ["..."]}}'
)


def _raise_for_status(response: httpx.Response) -> None:
    """Map DeepSeek HTTP error responses to typed LLMError subclasses."""
    if response.status_code < 400:
        return
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = None
    message = None
    if isinstance(body, dict):
        err = body.get("error") or {}
        if isinstance(err, dict):
            message = err.get("message")
    detail = message or response.text[:300] or response.reason_phrase
    if status == 401 or status == 403:
        raise LLMConfigError(f"DeepSeek authentication failed ({status}): {detail}")
    if status == 429:
        raise LLMRateLimitError(f"DeepSeek rate limit hit: {detail}")
    if 500 <= status < 600:
        raise LLMUnavailableError(f"DeepSeek returned {status}: {detail}")
    raise LLMConfigError(f"DeepSeek rejected the request ({status}): {detail}")


def _choice_dict(data: Any, idx: int = 0) -> dict[str, Any]:
    """Return data["choices"][idx] as a dict or raise typed errors."""
    if not isinstance(data, dict):
        raise LLMInvalidOutputError("DeepSeek response is not a JSON object")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMInvalidOutputError("DeepSeek response is missing `choices`")
    choice = choices[idx]
    if not isinstance(choice, dict):
        raise LLMInvalidOutputError("DeepSeek `choices[0]` is not an object")
    return choice


def _finish_reason(data: Any) -> Optional[str]:
    try:
        choice = _choice_dict(data)
    except LLMInvalidOutputError:
        return None
    reason = choice.get("finish_reason")
    return reason if isinstance(reason, str) else None


class DeepSeekProvider(BaseLLMProvider):
    def __init__(
        self, api_key: Optional[str] = None, model: Optional[str] = None
    ):
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise LLMConfigError(
                "Missing API key: set DEEPSEEK_API_KEY or configure the provider."
            )
        self.api_key = api_key
        self.model = model or os.environ.get("LLM_MODEL", "deepseek-chat")
        self.base_url = "https://api.deepseek.com/v1/chat/completions"

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        system_msg, user_msg = build_prompt(package)
        logger.info("Calling DeepSeek model=%s", self.model)

        schema = IncidentReport.model_json_schema()
        json_instruction = _JSON_INSTRUCTION_TEMPLATE.format(
            schema=json.dumps(schema, indent=2)
        )

        max_tokens = int(
            os.environ.get("LLM_MAX_TOKENS", _DEFAULT_MAX_TOKENS)
        )
        async with httpx.AsyncClient() as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        self.base_url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": system_msg + json_instruction,
                                },
                                {"role": "user", "content": user_msg},
                            ],
                            "max_tokens": max_tokens,
                            "response_format": {"type": "json_object"},
                        },
                        timeout=60,
                    )
                except httpx.TimeoutException as e:
                    raise LLMUnavailableError(
                        f"DeepSeek request timed out: {e}"
                    ) from e
                except httpx.HTTPError as e:
                    raise LLMUnavailableError(
                        f"DeepSeek connection error: {e}"
                    ) from e

                _raise_for_status(response)
                try:
                    data = response.json()
                except ValueError as e:
                    raise LLMInvalidOutputError(
                        f"DeepSeek returned a non-JSON HTTP response: {e}"
                    ) from e

                choice = _choice_dict(data)
                message = choice.get("message")
                content = ""
                if isinstance(message, dict):
                    raw_content = message.get("content")
                    if isinstance(raw_content, str):
                        content = raw_content

                finish_reason = choice.get("finish_reason")
                finish_reason = (
                    finish_reason if isinstance(finish_reason, str) else None
                )

                if not content:
                    if attempt == 0 and max_tokens < _RETRY_MAX_TOKENS:
                        max_tokens = _RETRY_MAX_TOKENS
                        logger.warning(
                            "DeepSeek returned empty content (finish_reason=%s); "
                            "retrying with max_tokens=%s",
                            finish_reason,
                            max_tokens,
                        )
                        continue
                    raise LLMTruncationError(
                        f"DeepSeek returned no content (finish_reason={finish_reason})"
                    )

                try:
                    raw_json = json.loads(content)
                except json.JSONDecodeError as e:
                    truncated = (
                        finish_reason == "length" or attempt == 0
                        and max_tokens < _RETRY_MAX_TOKENS
                    )
                    if truncated and attempt == 0 and max_tokens < _RETRY_MAX_TOKENS:
                        max_tokens = _RETRY_MAX_TOKENS
                        logger.warning(
                            "DeepSeek returned invalid JSON (finish_reason=%s); "
                            "retrying with max_tokens=%s",
                            finish_reason,
                            max_tokens,
                        )
                        continue
                    if finish_reason == "length":
                        raise LLMTruncationError(
                            f"DeepSeek returned truncated JSON (finish_reason=length): {e}"
                        ) from e
                    raise LLMInvalidOutputError(
                        f"DeepSeek returned non-JSON output (finish_reason={finish_reason}): {e}"
                    ) from e

                try:
                    return IncidentReport.model_validate(raw_json)
                except ValidationError as e:
                    raise LLMSchemaError(
                        f"DeepSeek output did not match schema: {e}"
                    ) from e

        raise RuntimeError("DeepSeek analysis did not return a result")
