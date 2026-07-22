import logging
import os

from k8s_llm_shared import EvidencePackage, IncidentReport
from openai import (
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)

from app.llm.base import BaseLLMProvider
from app.prompts import build_prompt

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

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
            raise RuntimeError(
                f"Output truncated (increase LLM_MAX_TOKENS): {e}"
            ) from e
        except ContentFilterFinishReasonError as e:
            raise RuntimeError(
                f"Content filtered by safety system: {e}"
            ) from e

        message = completion.choices[0].message
        if message.parsed is None:
            raise ValueError(
                f"No structured output (refusal={message.refusal!r})"
            )
        return message.parsed
