"""k8s-llm-shared — shared contract models for the analyser platform.

This package is the Python expression of the contracts SSOT (contracts/).
See contracts/README.md for the alignment rules these models follow.
"""

from k8s_llm_shared.enums import (
    EvidenceSource,
    FailureCategory,
    JobStatus,
    ProviderId,
    Severity,
)
from k8s_llm_shared.errors import ERROR_BASE_URL, ProblemDetail
from k8s_llm_shared.ids import new_id, utc_now_iso
from k8s_llm_shared.models import (
    AnalysisRequest,
    EvidenceItem,
    EvidencePackage,
    HealthResponse,
    IncidentReport,
    JobCreated,
    JobState,
    LatencyPoint,
    ProviderInfo,
    RawEvidence,
    ReportSummary,
    SaveJobRequest,
    SaveReportRequest,
    SaveReportResponse,
    ScenarioApplyResponse,
    ScenarioSummary,
    SseDoneEvent,
    SseFailedEvent,
    SseStageEvent,
    StatsResponse,
)

__all__ = [
    "ERROR_BASE_URL",
    "AnalysisRequest",
    "EvidenceItem",
    "EvidencePackage",
    "EvidenceSource",
    "FailureCategory",
    "HealthResponse",
    "IncidentReport",
    "JobCreated",
    "JobState",
    "JobStatus",
    "LatencyPoint",
    "ProblemDetail",
    "ProviderId",
    "ProviderInfo",
    "RawEvidence",
    "ReportSummary",
    "SaveJobRequest",
    "SaveReportRequest",
    "SaveReportResponse",
    "ScenarioApplyResponse",
    "ScenarioSummary",
    "Severity",
    "SseDoneEvent",
    "SseFailedEvent",
    "SseStageEvent",
    "StatsResponse",
    "new_id",
    "utc_now_iso",
]

__version__ = "1.0.0"
