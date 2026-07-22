import type { components } from "./api";

// Enum unions
export type FailureCategory = components["schemas"]["failure_category"];
export type Severity = components["schemas"]["severity"];
export type JobStatus = components["schemas"]["job_status_enum"];
export type EvidenceSource = components["schemas"]["evidence_source"];

// Core domain models
export type EvidenceItem = components["schemas"]["evidence_item"];
export type IncidentReport = components["schemas"]["incident_report"];
export type ReportSummary = components["schemas"]["report_summary"];

// Job models
export type AnalysisRequest = components["schemas"]["analysis_request"];
export type JobCreated = components["schemas"]["job_created"];
export type JobState = components["schemas"]["job_state"];

// SSE event payloads
export type SseStageEvent = components["schemas"]["sse_stage_event"];
export type SseDoneEvent = components["schemas"]["sse_done_event"];
export type SseFailedEvent = components["schemas"]["sse_failed_event"];

// Scenario models
export type ScenarioSummary = components["schemas"]["scenario_summary"];
export type ScenarioApplyResponse =
  components["schemas"]["scenario_apply_response"];

// Stats
export type StatsResponse = components["schemas"]["stats_response"];
export type LatencyPoint = NonNullable<
  StatsResponse["latency_series"]
>[number];

// Health
export type HealthResponse = components["schemas"]["health_response"] & {
  cluster?: string | null;
};

// RFC 7807 Problem Details
export type ProblemDetails = components["schemas"]["error"];

// Pagination envelopes (inline in the OpenAPI path definitions)
export interface Paginated<T> {
  items: T[];
  count: number;
  limit: number;
  offset: number;
}

export type JobListResponse = Paginated<JobState>;
export type ReportListResponse = Paginated<ReportSummary>;

export interface ScenarioListResponse {
  items: ScenarioSummary[];
}

export interface ResetResponse {
  reset: boolean;
}

export type StatsRange = "24h" | "7d" | "30d";
