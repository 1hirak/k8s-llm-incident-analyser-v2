import logging
import os
from typing import Optional

import anthropic
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from k8s_llm_shared import EvidencePackage, IncidentReport

from app.llm.base import BaseLLMProvider
from app.llm.errors import (
    LLMConfigError,
    LLMContentFilterError,
    LLMUnavailableError,
    LLMRateLimitError,
)
from app.prompts import build_prompt

logger = logging.getLogger(__name__)


def _api_key_or_raise(env_var: str) -> str:
    value = os.environ.get(env_var)
    if not value:
        raise LLMConfigError(
            f"Missing API key: set {env_var} or configure the provider."
        )
    return value


class AnthropicProvider(BaseLLMProvider):
    def __init__(
        self, api_key: Optional[str] = None, model: Optional[str] = None
    ):
        self.api_key = api_key or _api_key_or_raise("ANTHROPIC_API_KEY")
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.model = model or os.environ.get(
            "LLM_MODEL", "claude-haiku-4-5-20251001"
        )

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        system_msg, user_msg = build_prompt(package)
        logger.info("Calling Anthropic model=%s", self.model)

        try:
            response = await self.client.messages.parse(
                model=self.model,
                max_tokens=int(os.environ.get("LLM_MAX_TOKENS", 2000)),
                system=system_msg,
                messages=[{"role": "user", "content": user_msg}],
                output_format=IncidentReport,
            )
        except RateLimitError as e:
            raise LLMRateLimitError(f"Anthropic rate limit hit: {e}") from e
        except (AuthenticationError, PermissionDeniedError) as e:
            raise LLMConfigError(
                f"Anthropic authentication failed: {e}"
            ) from e
        except (NotFoundError, BadRequestError) as e:
            raise LLMConfigError(
                f"Anthropic rejected the request: {e}"
            ) from e
        except APITimeoutError as e:
            raise LLMUnavailableError(
                f"Anthropic request timed out: {e}"
            ) from e
        except APIConnectionError as e:
            raise LLMUnavailableError(
                f"Anthropic connection error: {e}"
            ) from e
        except APIStatusError as e:
            raise LLMUnavailableError(
                f"Anthropic returned {e.status_code}: {e}"
            ) from e

        parsed = response.content[0].parsed_output
        if parsed is None:
            text = response.content[0].text if response.content else ""
            logger.warning("Anthropic returned no parsed output; raw=%s", text)
            raise LLMContentFilterError(
                f"Anthropic returned no structured output (raw={text!r})"
            )
        return parsed
