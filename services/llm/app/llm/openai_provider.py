import logging
import os
from typing import Optional

from k8s_llm_shared import EvidencePackage, IncidentReport
from openai import (
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from openai import APIStatusError, APITimeoutError, APIConnectionError

from app.llm.base import BaseLLMProvider
from app.llm.errors import (
    LLMConfigError,
    LLMContentFilterError,
    LLMRateLimitError,
    LLMTruncationError,
    LLMUnavailableError,
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


class OpenAIProvider(BaseLLMProvider):
    def __init__(
        self, api_key: Optional[str] = None, model: Optional[str] = None
    ):
        self.api_key = api_key or _api_key_or_raise("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        system_msg, user_msg = build_prompt(package)
        logger.info("Calling OpenAI model=%s", self.model)

        try:
            completion = await self.client.chat.completions.parse(
                model=self.model,
                max_tokens=int(os.environ.get("LLM_MAX_TOKENS", 2000)),
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                response_format=IncidentReport,
            )
        except LengthFinishReasonError as e:
            raise LLMTruncationError(
                f"Output truncated (increase LLM_MAX_TOKENS): {e}"
            ) from e
        except ContentFilterFinishReasonError as e:
            raise LLMContentFilterError(
                f"Content filtered by safety system: {e}"
            ) from e
        except RateLimitError as e:
            raise LLMRateLimitError(f"OpenAI rate limit hit: {e}") from e
        except (AuthenticationError, PermissionDeniedError) as e:
            raise LLMConfigError(f"OpenAI authentication failed: {e}") from e
        except (NotFoundError, BadRequestError) as e:
            raise LLMConfigError(f"OpenAI rejected the request: {e}") from e
        except APITimeoutError as e:
            raise LLMUnavailableError(
                f"OpenAI request timed out: {e}"
            ) from e
        except APIConnectionError as e:
            raise LLMUnavailableError(
                f"OpenAI connection error: {e}"
            ) from e
        except APIStatusError as e:
            raise LLMUnavailableError(
                f"OpenAI returned {e.status_code}: {e}"
            ) from e

        message = completion.choices[0].message
        if message.parsed is None:
            raise LLMContentFilterError(
                f"No structured output (refusal={message.refusal!r})"
            )
        return message.parsed
