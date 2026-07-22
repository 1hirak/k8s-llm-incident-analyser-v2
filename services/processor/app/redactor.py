"""Log redactor — masks PII and secrets before LLM ingestion.

Moved from the monolith (app/core/redactor.py). Uses Pydantic model_copy
instead of dataclasses.replace now that EvidencePackage is a shared
Pydantic contract model.
"""

import re

from k8s_llm_shared import EvidencePackage

REDACT_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*[\S]+"), "[PASSWORD=REDACTED]"),
    (re.compile(
        r"(?i)(api[_-]?key|apikey|token|secret)[\s=:\"]+[A-Za-z0-9+/=_\-]{8,}"
    ), "[API_KEY=REDACTED]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[ANTHROPIC_KEY=REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[OPENAI_KEY=REDACTED]"),
    (re.compile(r"(postgres|mysql|mongodb|redis)://[^\s'\"]+"), "[DB_URL=REDACTED]"),
    (re.compile(r"(?i)(Authorization|Bearer)\s+[A-Za-z0-9+/=]{20,}"), "[AUTH_HEADER=REDACTED]"),
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[EMAIL=REDACTED]"),
]


class LogRedactor:
    def _redact_text(self, text: str) -> str:
        for pattern, replacement in REDACT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def redact(self, package: EvidencePackage) -> EvidencePackage:
        return package.model_copy(
            update={
                "current_logs": self._redact_text(package.current_logs),
                "previous_logs": self._redact_text(package.previous_logs),
                "pod_status_summary": self._redact_text(package.pod_status_summary),
                "k8s_events_filtered": self._redact_text(package.k8s_events_filtered),
            }
        )
