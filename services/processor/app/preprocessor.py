"""Log preprocessor — noise/signal filtering with context windows.

Moved from the monolith (app/core/preprocessor.py). EvidencePackage is now
the shared Pydantic contract model instead of a local dataclass.
"""

import re

from k8s_llm_shared import EvidencePackage, RawEvidence

NOISE_PATTERNS = [
    re.compile(r"\bGET /health\b"),
    re.compile(r"\bGET /ready\b"),
    re.compile(r"\bGET /metrics\b"),
    re.compile(r"^\s*$"),
]

SIGNAL_PATTERNS = [
    re.compile(
        r"\b(error|exception|traceback|fatal|critical|failed|refused|timeout)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(OOMKilled|CrashLoopBackOff|ImagePullBackOff|BackOff|Unhealthy)\b"
    ),
    re.compile(
        r"\b(missing|not found|permission denied|address already in use)\b",
        re.IGNORECASE,
    ),
]


class LogPreprocessor:
    def __init__(self, max_log_lines: int = 100, context_window: int = 3):
        self.max_log_lines = max_log_lines
        self.context_window = context_window

    def _is_noise(self, line: str) -> bool:
        return any(p.search(line) for p in NOISE_PATTERNS)

    def _is_signal(self, line: str) -> bool:
        return any(p.search(line) for p in SIGNAL_PATTERNS)

    def _filter_with_context(self, raw_text: str) -> str:
        lines = raw_text.splitlines()
        keep_indices = set()

        for i, line in enumerate(lines):
            if self._is_signal(line) and not self._is_noise(line):
                start = max(0, i - self.context_window)
                end = min(len(lines), i + self.context_window + 1)
                for j in range(start, end):
                    keep_indices.add(j)

        seen = set()
        result = []
        for i in sorted(keep_indices):
            stripped = lines[i].strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                result.append(lines[i])

        return "\n".join(result[:self.max_log_lines])

    def _extract_events(self, events_raw: str) -> str:
        return "\n".join(
            line for line in events_raw.splitlines()
            if "Warning" in line or self._is_signal(line)
        )

    def process(self, evidence: RawEvidence) -> EvidencePackage:
        return EvidencePackage(
            namespace=evidence.namespace,
            pod_name=evidence.pod_name,
            target_kind=evidence.target_kind,
            target_name=evidence.target_name,
            target_context=evidence.target_context,
            pod_names=evidence.pod_names,
            current_logs=self._filter_with_context(evidence.current_logs),
            previous_logs=self._filter_with_context(evidence.previous_logs),
            pod_status_summary=evidence.pod_status[:2000],
            k8s_events_filtered=self._extract_events(evidence.k8s_events),
            restart_count=evidence.restart_count,
        )
