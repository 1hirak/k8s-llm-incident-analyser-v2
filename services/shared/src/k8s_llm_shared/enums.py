"""Enum definitions with exact parity across all contract pillars.

Changing any of these value sets is a breaking change requiring a major
version bump of the contracts package (see contracts/README.md §4.3).
"""

from typing import Literal

# Exactly 8 values — parity: SQLite CHECK, OpenAPI enum, TS union
FailureCategory = Literal[
    "crash",
    "config",
    "dependency",
    "network",
    "image",
    "resource",
    "probe",
    "unknown",
]

# Exactly 4 values — parity: SQLite CHECK, OpenAPI enum, TS union
Severity = Literal["low", "medium", "high", "critical"]

# Exactly 7 values — parity: SQLite CHECK, Redis hash field, SSE payload
JobStatus = Literal[
    "queued",
    "collecting",
    "processing",
    "llm_call",
    "persisting",
    "done",
    "failed",
]

# Exactly 4 values — source of an evidence item
EvidenceSource = Literal[
    "pod_log",
    "previous_pod_log",
    "kubernetes_event",
    "pod_status",
]

# Exactly 4 values — LLM provider identifiers
ProviderId = Literal["mock", "openai", "anthropic", "deepseek"]
