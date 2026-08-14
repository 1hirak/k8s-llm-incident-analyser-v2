import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useDiagnosisJob } from "@/hooks/use-diagnosis-job";
import { ApiError } from "@/lib/api";
import type { JobStreamEvent } from "@/lib/sse";

const createJob = vi.fn();
const getJob = vi.fn();
const streamJob = vi.fn<
  (
    jobId: string,
    onEvent: (event: JobStreamEvent) => void,
    onError?: (event: Event) => void,
  ) => () => void
>();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createJob: (...args: Parameters<typeof import("@/lib/api").createJob>) =>
      createJob(...args),
    getJob: (...args: Parameters<typeof import("@/lib/api").getJob>) =>
      getJob(...args),
  };
});

vi.mock("@/lib/sse", () => ({
  streamJob: (
    jobId: string,
    onEvent: (event: JobStreamEvent) => void,
    onError?: (event: Event) => void,
  ) => streamJob(jobId, onEvent, onError),
}));

describe("useDiagnosisJob", () => {
  beforeEach(() => {
    createJob.mockReset();
    getJob.mockReset();
    streamJob.mockReset();
    streamJob.mockImplementation(() => () => {});
  });

  it("starts idle", () => {
    const { result } = renderHook(() => useDiagnosisJob());
    expect(result.current.phase).toBe("idle");
  });

  it("creates job and enters running phase", async () => {
    createJob.mockResolvedValue({ job_id: "job-123", status: "queued" });
    const { result } = renderHook(() => useDiagnosisJob());

    await act(async () => {
      await result.current.startDiagnosis("demo", "demo-app");
    });

    expect(createJob).toHaveBeenCalledWith({
      namespace: "demo",
      pod_name: "demo-app",
      target_kind: "Pod",
    });
    expect(result.current.phase).toBe("running");
  });

  it("handles job creation failure", async () => {
    createJob.mockRejectedValue(
      new ApiError(0, null, "gateway unavailable"),
    );
    const onFailed = vi.fn();
    const { result } = renderHook(() => useDiagnosisJob({ onFailed }));

    await act(async () => {
      await result.current.startDiagnosis("demo", "demo-app");
    });

    await waitFor(() => expect(result.current.phase).toBe("failed"));
    expect(result.current.submitError).toContain("gateway unavailable");
    expect(onFailed).toHaveBeenCalledWith(
      expect.objectContaining({
        job_id: "",
        error: "gateway unavailable",
      }),
    );
  });

  it("accumulates a deduplicated activity trace from SSE events", async () => {
    createJob.mockResolvedValue({ job_id: "job-123", status: "queued" });
    let onEvent: (event: JobStreamEvent) => void = () => {};
    streamJob.mockImplementation((_jobId, cb) => {
      onEvent = cb;
      return () => {};
    });

    const { result } = renderHook(() => useDiagnosisJob());
    await act(async () => {
      await result.current.startDiagnosis("demo", "demo-app");
    });

    act(() => {
      onEvent({
        type: "stage",
        data: {
          event: "stage",
          job_id: "job-123",
          status: "llm_call",
          stage: "Calling mock (none)",
          updated_at: "2026-08-13T07:00:00Z",
        },
      });
      // Duplicate replay, e.g. after an SSE resubscribe — must be dropped.
      onEvent({
        type: "stage",
        data: {
          event: "stage",
          job_id: "job-123",
          status: "llm_call",
          stage: "Calling mock (none)",
          updated_at: "2026-08-13T07:00:01Z",
        },
      });
      onEvent({
        type: "stage",
        data: {
          event: "stage",
          job_id: "job-123",
          status: "persisting",
          stage: "Saving report",
          updated_at: "2026-08-13T07:00:03Z",
        },
      });
      onEvent({
        type: "done",
        data: {
          event: "done",
          job_id: "job-123",
          status: "done",
          incident_id: "inc-1",
          active_error: true,
          latency_ms: 4000,
        },
      });
    });

    const trace = result.current.activity.map((e) => `${e.kind}:${e.status}`);
    expect(trace).toEqual(["stage:llm_call", "stage:persisting", "done:done"]);
    expect(result.current.activity[0].detail).toBe("Calling mock (none)");
    expect(result.current.activity[2].latencyMs).toBe(4000);
  });

  it("clears the activity trace on reset", async () => {
    createJob.mockResolvedValue({ job_id: "job-123", status: "queued" });
    let onEvent: (event: JobStreamEvent) => void = () => {};
    streamJob.mockImplementation((_jobId, cb) => {
      onEvent = cb;
      return () => {};
    });

    const { result } = renderHook(() => useDiagnosisJob());
    await act(async () => {
      await result.current.startDiagnosis("demo", "demo-app");
    });
    act(() => {
      onEvent({
        type: "stage",
        data: {
          event: "stage",
          job_id: "job-123",
          status: "collecting",
          stage: "Collecting evidence",
          updated_at: "2026-08-13T07:00:00Z",
        },
      });
    });
    expect(result.current.activity).toHaveLength(1);

    act(() => {
      result.current.reset();
    });
    expect(result.current.activity).toHaveLength(0);
  });
});
