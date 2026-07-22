import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiError, API_BASE_URL, getHealth, createJob, getJob, listJobs, listReports, getReport, getStats, listScenarios, applyScenario, resetScenarios } from "@/lib/api";

const mockFetch = (status: number, body: unknown, ok = status >= 200 && status < 300) => {
  return vi.fn().mockResolvedValue({ ok, status, json: async () => body } as Response);
};

beforeEach(() => { vi.restoreAllMocks(); });

describe("ApiError", () => {
  it("creates with status and problem", () => {
    const err = new ApiError(404, { status: 404, title: "Not found", detail: "missing" });
    expect(err.status).toBe(404);
    expect(err.message).toBe("missing");
  });
  it("falls back to title when no detail", () => {
    const err = new ApiError(500, { status: 500, title: "Server error" });
    expect(err.message).toBe("Server error");
  });
  it("generic message when no problem", () => {
    const err = new ApiError(502, null);
    expect(err.message).toBe("Request failed with status 502");
  });
  it("accepts explicit message override", () => {
    const err = new ApiError(500, { status: 500, title: "Server error" }, "Custom");
    expect(err.message).toBe("Custom");
  });
  it("instanceof Error", () => {
    expect(new ApiError(500, null)).toBeInstanceOf(Error);
  });
  it("name is ApiError", () => {
    expect(new ApiError(500, null).name).toBe("ApiError");
  });
  it("problem can be null", () => {
    expect(new ApiError(200, null).problem).toBeNull();
  });
});

describe("API_BASE_URL", () => {
  it("is non-empty string", () => {
    expect(typeof API_BASE_URL).toBe("string");
    expect(API_BASE_URL.length).toBeGreaterThan(0);
  });
});

describe("getHealth", () => {
  it("returns health on 200", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { status: "ok", service: "test", version: "0.1" }));
    const data = await getHealth();
    expect(data.status).toBe("ok");
  });
  it("throws ApiError on 500", async () => {
    vi.stubGlobal("fetch", mockFetch(500, { status: 500, title: "err" }, false));
    await expect(getHealth()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("createJob", () => {
  it("returns JobCreated on 202", async () => {
    vi.stubGlobal("fetch", mockFetch(202, { job_id: "j1", status: "queued" }));
    const data = await createJob({ namespace: "demo", pod_name: "pod" });
    expect(data.status).toBe("queued");
  });
});

describe("getJob", () => {
  it("fetches job state", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { job_id: "j1", namespace: "n", pod_name: "p", status: "done", created_at: "t", updated_at: "t" }));
    const data = await getJob("j1");
    expect(data.status).toBe("done");
  });
});

describe("listJobs", () => {
  it("returns empty list", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { items: [], count: 0, limit: 20, offset: 0 }));
    const data = await listJobs();
    expect(data.count).toBe(0);
  });
  it("passes query params", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], count: 0, limit: 20, offset: 0 }) });
    vi.stubGlobal("fetch", fetcher);
    await listJobs({ status: "done", limit: 10, offset: 5 });
    expect(fetcher.mock.calls[0][0]).toContain("status=done");
    expect(fetcher.mock.calls[0][0]).toContain("offset=5");
  });
});

describe("listReports", () => {
  it("filters by category and namespace", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], count: 0, limit: 20, offset: 0 }) });
    vi.stubGlobal("fetch", fetcher);
    await listReports({ category: "crash", namespace: "demo" });
    const url = String(fetcher.mock.calls[0][0]);
    expect(url).toContain("category=crash");
    expect(url).toContain("namespace=demo");
  });
  it("omits empty filters", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], count: 0, limit: 20, offset: 0 }) });
    vi.stubGlobal("fetch", fetcher);
    await listReports({});
    const url = String(fetcher.mock.calls[0][0]);
    expect(url).not.toContain("?");
  });
});

describe("getReport", () => {
  it("returns fully-formed report", async () => {
    vi.stubGlobal("fetch", mockFetch(200, {
      incident_id: "inc-1", incident_summary: "summary text long enough",
      likely_root_cause: "root cause long enough text",
      affected_component: "app", failure_category: "crash", severity: "high",
      confidence: 0.9, supporting_evidence: [],
      suggested_fix: "fix", recommended_commands: [], human_verification_steps: [],
      created_at: "now",
    }));
    const data = await getReport("inc-1");
    expect(data.incident_id).toBe("inc-1");
    expect(data.failure_category).toBe("crash");
  });
});

describe("getStats", () => {
  it("defaults range to 7d", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ total_reports: 0, reports_24h: 0, mean_latency_ms: 0, mean_confidence: 0, category_counts: {} }) });
    vi.stubGlobal("fetch", fetcher);
    await getStats();
    expect(String(fetcher.mock.calls[0][0])).toContain("range=7d");
  });
  it("accepts 24h", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ total_reports: 0, reports_24h: 0, mean_latency_ms: 0, mean_confidence: 0, category_counts: {} }) });
    vi.stubGlobal("fetch", fetcher);
    await getStats("24h");
    expect(String(fetcher.mock.calls[0][0])).toContain("range=24h");
  });
});

describe("listScenarios", () => {
  it("returns list", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { items: [{ scenario_id: "01", name: "t", category: "crash", description: "d" }] }));
    const data = await listScenarios();
    expect(data.items).toHaveLength(1);
  });
});

describe("applyScenario", () => {
  it("posts and returns result", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { applied: true, scenario_id: "05-oom", fault_description: "OOM" }));
    const data = await applyScenario("05-oom");
    expect(data.applied).toBe(true);
  });
  it("throws ApiError on 404", async () => {
    vi.stubGlobal("fetch", mockFetch(404, { status: 404, title: "Not found" }, false));
    await expect(applyScenario("99-nope")).rejects.toBeInstanceOf(ApiError);
  });
  it("throws ApiError on 409", async () => {
    vi.stubGlobal("fetch", mockFetch(409, { status: 409, title: "Conflict" }, false));
    await expect(applyScenario("05-oom")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("resetScenarios", () => {
  it("posts and returns reset", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { reset: true }));
    const data = await resetScenarios();
    expect(data.reset).toBe(true);
  });
});

describe("network error", () => {
  it("throws ApiError with status 0 on fetch reject", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection refused")));
    await expect(getHealth()).rejects.toMatchObject({ status: 0 });
  });
});
