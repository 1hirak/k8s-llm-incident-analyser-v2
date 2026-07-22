"""Shared Pydantic models — the Python expression of contracts/api/*.yaml.

All field names are snake_case (contracts/README.md §4.1). All IDs are
UUIDv7 strings (§4.4). All timestamps are ISO 8601 strings (§4.5).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from k8s_llm_shared.enums import (
    EvidenceSource,
    FailureCategory,
    JobStatus,
    ProviderId,
    Severity,
)
from k8s_llm_shared.ids import new_id, utc_now_iso

# ---------------------------------------------------------------------------
# Core domain models (gateway.yaml)
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    source: EvidenceSource
    pod: str
    timestamp: Optional[str] = None
    evidence: str


class IncidentReport(BaseModel):
    """The canonical incident report — contract between LLM providers and
    the rest of the system."""

    incident_id: str = Field(default_factory=new_id)
    incident_summary: str = Field(..., min_length=10)
    likely_root_cause: str = Field(..., min_length=10)
    affected_component: str
    failure_category: FailureCategory
    severity: Severity
    confidence: float = Field(..., ge=0.0, le=1.0)
    supporting_evidence: list[EvidenceItem] = Field(..., min_length=1)
    suggested_fix: str
    recommended_commands: list[str]
    human_verification_steps: list[str]
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = {"extra": "ignore"}


class ReportSummary(BaseModel):
    incident_id: str
    namespace: str
    pod_name: str
    failure_category: FailureCategory
    severity: Severity
    confidence: float = Field(..., ge=0.0, le=1.0)
    incident_summary: str
    created_at: str


# ---------------------------------------------------------------------------
# Internal pipeline models (orchestrator.yaml)
# ---------------------------------------------------------------------------


class RawEvidence(BaseModel):
    """Collector output / processor input. Never exposed in the public API."""

    namespace: str
    pod_name: str
    current_logs: str = ""
    previous_logs: str = ""
    pod_status: str = ""
    k8s_events: str = ""
    restart_count: int = 0
    # kubectl jsonpath={.status.containerStatuses} returns a JSON array
    container_states: list[Any] = Field(default_factory=list)


class EvidencePackage(BaseModel):
    """Processor output / LLM input (preprocessed + redacted)."""

    namespace: str
    pod_name: str
    current_logs: str
    previous_logs: str
    pod_status_summary: str
    k8s_events_filtered: str
    restart_count: int


# ---------------------------------------------------------------------------
# Job models (gateway.yaml / orchestrator.yaml)
# ---------------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    namespace: str = "demo"
    pod_name: str


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus


class JobState(BaseModel):
    """Full job state. Parity: Redis hash job:{job_id}, SQLite analysis_jobs."""

    job_id: str
    namespace: str
    pod_name: str
    status: JobStatus
    stage: Optional[str] = None
    incident_id: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# SSE event payloads (gateway.yaml)
# ---------------------------------------------------------------------------


class SseStageEvent(BaseModel):
    event: str = "stage"
    job_id: str
    status: JobStatus
    stage: str
    updated_at: str


class SseDoneEvent(BaseModel):
    event: str = "done"
    job_id: str
    status: str = "done"
    incident_id: str
    failure_category: FailureCategory
    severity: Severity
    latency_ms: int


class SseFailedEvent(BaseModel):
    event: str = "failed"
    job_id: str
    status: str = "failed"
    error: str
    latency_ms: int


# ---------------------------------------------------------------------------
# Scenario models (gateway.yaml / scenario.yaml)
# ---------------------------------------------------------------------------


class ScenarioSummary(BaseModel):
    scenario_id: str
    name: str
    category: FailureCategory
    description: str
    severity: Optional[Severity] = None


class ScenarioApplyResponse(BaseModel):
    applied: bool
    scenario_id: str
    fault_description: Optional[str] = None


# ---------------------------------------------------------------------------
# Stats models (gateway.yaml / reports.yaml)
# ---------------------------------------------------------------------------


class LatencyPoint(BaseModel):
    timestamp: str
    latency_ms: int


class StatsResponse(BaseModel):
    total_reports: int
    reports_24h: int
    mean_latency_ms: float
    mean_confidence: float = Field(..., ge=0.0, le=1.0)
    category_counts: dict[str, int]
    latency_series: list[LatencyPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reports-svc internal models (reports.yaml)
# ---------------------------------------------------------------------------


class SaveReportRequest(BaseModel):
    report: IncidentReport
    namespace: str
    pod_name: str
    job_id: str


class SaveReportResponse(BaseModel):
    incident_id: str


class SaveJobRequest(BaseModel):
    job_id: str
    namespace: str
    pod_name: str
    status: JobStatus
    stage: Optional[str] = None
    incident_id: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# LLM service models (llm.yaml)
# ---------------------------------------------------------------------------


class ProviderInfo(BaseModel):
    id: ProviderId
    name: str
    model: str
    available: bool


# ---------------------------------------------------------------------------
# Health (gateway.yaml §4.8)
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str
    provider: Optional[str] = None
    model: Optional[str] = None
    cluster: Optional[str] = None
