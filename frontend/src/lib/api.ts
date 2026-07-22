import type {
  AnalysisRequest,
  FailureCategory,
  HealthResponse,
  IncidentReport,
  JobCreated,
  JobListResponse,
  JobState,
  JobStatus,
  ProblemDetails,
  ReportListResponse,
  ResetResponse,
  ScenarioApplyResponse,
  ScenarioListResponse,
  Severity,
  StatsRange,
  StatsResponse,
} from "@/types";
import { logger } from "./logger";

const isServer = typeof window === "undefined";

export const API_BASE_URL = isServer
  ? process.env.INTERNAL_API_URL ?? "http://gateway:8000"
  : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Error thrown for any non-2xx gateway response. Carries the RFC 7807
 * Problem Details body when the gateway provided one.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | null;

  constructor(status: number, problem: ProblemDetails | null, message?: string) {
    super(
      message ??
        problem?.detail ??
        problem?.title ??
        `Request failed with status ${status}`,
    );
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

type QueryParams = Record<string, string | number | undefined | null>;

function buildQuery(params: QueryParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch {
    logger.error({ msg: "api_fetch_failed", path, baseUrl: API_BASE_URL });
    throw new ApiError(
      0,
      null,
      `Could not reach the API gateway at ${API_BASE_URL}`,
    );
  }

  if (!res.ok) {
    let problem: ProblemDetails | null = null;
    try {
      problem = (await res.json()) as ProblemDetails;
    } catch {
      // Non-JSON error body — keep the null problem.
    }
    logger.error({ msg: "api_response_error", status: res.status, path, problem });
    throw new ApiError(res.status, problem);
  }

  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { cache: "no-store" });
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export function createJob(body: AnalysisRequest): Promise<JobCreated> {
  return request<JobCreated>("/api/jobs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface ListJobsParams {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}

export function listJobs(params: ListJobsParams = {}): Promise<JobListResponse> {
  return request<JobListResponse>(
    `/api/jobs${buildQuery({
      status: params.status,
      limit: params.limit,
      offset: params.offset,
    })}`,
    { cache: "no-store" },
  );
}

export function getJob(jobId: string): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}`, { cache: "no-store" });
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export interface ListReportsParams {
  namespace?: string;
  pod_name?: string;
  category?: FailureCategory;
  severity?: Severity;
  limit?: number;
  offset?: number;
}

export function listReports(
  params: ListReportsParams = {},
): Promise<ReportListResponse> {
  return request<ReportListResponse>(
    `/api/reports${buildQuery({
      namespace: params.namespace,
      pod_name: params.pod_name,
      category: params.category,
      severity: params.severity,
      limit: params.limit,
      offset: params.offset,
    })}`,
    { cache: "no-store" },
  );
}

export function getReport(incidentId: string): Promise<IncidentReport> {
  return request<IncidentReport>(`/api/reports/${incidentId}`, {
    cache: "no-store",
  });
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export function getStats(range: StatsRange = "7d"): Promise<StatsResponse> {
  return request<StatsResponse>(
    `/api/stats${buildQuery({ range })}`,
    { cache: "no-store" },
  );
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

export function listScenarios(): Promise<ScenarioListResponse> {
  return request<ScenarioListResponse>("/api/scenarios", {
    cache: "no-store",
  });
}

export function applyScenario(
  scenarioId: string,
): Promise<ScenarioApplyResponse> {
  return request<ScenarioApplyResponse>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/apply`,
    { method: "POST" },
  );
}

export function resetScenarios(): Promise<ResetResponse> {
  return request<ResetResponse>("/api/scenarios/reset", { method: "POST" });
}
