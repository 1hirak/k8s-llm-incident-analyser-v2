import json
import logging
import os

import httpx
from k8s_llm_shared import EvidencePackage, IncidentReport

from app.llm.base import BaseLLMProvider
from app.prompts import build_prompt

logger = logging.getLogger(__name__)

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


class DeepSeekProvider(BaseLLMProvider):
    def __init__(self):
        self.api_key = os.environ["DEEPSEEK_API_KEY"]
        self.model = os.environ.get("LLM_MODEL", "deepseek-chat")
        self.base_url = "https://api.deepseek.com/v1/chat/completions"

    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        system_msg, user_msg = build_prompt(package)
        logger.info("Calling DeepSeek model=%s", self.model)

        schema = IncidentReport.model_json_schema()
        json_instruction = _JSON_INSTRUCTION_TEMPLATE.format(
            schema=json.dumps(schema, indent=2)
        )

        async with httpx.AsyncClient() as client:
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
                    "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", 2000)),
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            try:
                raw_json = json.loads(data["choices"][0]["message"]["content"])
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"DeepSeek returned non-JSON/truncated output: {e}"
                ) from e
            return IncidentReport.model_validate(raw_json)
