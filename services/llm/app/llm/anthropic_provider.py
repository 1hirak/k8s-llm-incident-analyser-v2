import logging
import os

import anthropic
from k8s_llm_shared import EvidencePackage, IncidentReport

from app.llm.base import BaseLLMProvider
from app.prompts import build_prompt

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseLLMProvider):
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        self.model = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        system_msg, user_msg = build_prompt(package)
        logger.info("Calling Anthropic model=%s", self.model)

        response = await self.client.messages.parse(
            model=self.model,
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", 2000)),
            system=system_msg,
            messages=[{"role": "user", "content": user_msg}],
            output_format=IncidentReport,
        )
        parsed = response.content[0].parsed_output
        if parsed is None:
            text = response.content[0].text if response.content else ""
            logger.warning("Anthropic returned no parsed output; raw=%s", text)
            raise ValueError("Anthropic returned no structured output")
        return parsed
