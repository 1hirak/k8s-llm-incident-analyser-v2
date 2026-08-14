import type { components } from "./api";

// Enum unions
export type FailureCategory = components["schemas"]["failure_category"];
export type Severity = components["schemas"]["severity"];
export type JobStatus = components["schemas"]["job_status_enum"];
export type EvidenceSource = components["schemas"]["evidence_source"];
export type TargetKind = components["schemas"]["target_kind"];
export type TargetOption = components["schemas"]["target_option"];

// Core domain models
export type EvidenceItem = components["schemas"]["evidence_item"];
export type AnalysisExplanation = components["schemas"]["analysis_explanation"];
export type AnalysisInputSummary = components["schemas"]["analysis_input_summary"];
export type IncidentReport = components["schemas"]["incident_report"];
export type RemediationAction = components["schemas"]["remediation_action"];
export type RemediationApprovalRequest =
  components["schemas"]["remediation_approval_request"];
export type RemediationCreateRequest =
  components["schemas"]["remediation_create_request"];
export type RemediationRecord = components["schemas"]["remediation_record"];
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

// Settings (LLM provider configuration)
export type ProviderInfo = components["schemas"]["provider_info"];
export type ProviderConfigRequest =
  components["schemas"]["provider_config_request"];
export type LLMConfigStatus = components["schemas"]["llm_config_status"];

export interface ProviderListResponse {
  items: ProviderInfo[];
}

export interface TargetListResponse {
  items: TargetOption[];
}

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

// Error queue (frontend-only persistence)
export type {
  ErrorQueueItem,
  ErrorQueueItemStatus,
} from "@/lib/error-queue";
