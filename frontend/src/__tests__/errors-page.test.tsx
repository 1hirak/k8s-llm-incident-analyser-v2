import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorsClient } from "@/app/errors/errors-client";
import {
  addErrorQueueItem,
  clearErrorQueue,
  loadErrorQueue,
} from "@/lib/error-queue";

const apiMocks = vi.hoisted(() => ({
  createJob: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  cancelActiveJobs: vi.fn(),
  resetScenarios: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    ...apiMocks,
  };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/lib/sse", () => ({
  streamJob: () => () => {},
}));

describe("ErrorsPage", () => {
  beforeEach(() => {
    clearErrorQueue();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.createJob.mockReset();
    apiMocks.getJob.mockReset();
    apiMocks.cancelJob.mockReset();
    apiMocks.cancelActiveJobs.mockReset();
    apiMocks.resetScenarios.mockReset();
  });

  it("renders empty state when no errors", async () => {
    render(<ErrorsClient />);
    expect(await screen.findByText("No errors yet")).toBeInTheDocument();
  });

  it("renders error cards", async () => {
    addErrorQueueItem({
      source: "scenario",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      category: "resource",
      severity: "high",
      status: "triggered",
    });

    render(<ErrorsClient />);
    expect((await screen.findAllByText("OOM Killed")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Needs diagnosis").length).toBeGreaterThan(0);
  });

  it("can switch to fixed filter", async () => {
    const item = addErrorQueueItem({
      source: "scenario",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    const { updateErrorQueueItem } = await import("@/lib/error-queue");
    updateErrorQueueItem(item.id, { status: "fixed" });

    render(<ErrorsClient />);
    expect(await screen.findByRole("tab", { name: /fixed/i })).toBeInTheDocument();
  });

  it("clears all queue items", async () => {
    addErrorQueueItem({
      source: "scenario",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });

    render(<ErrorsClient />);
    await userEvent.click(
      await screen.findByRole("button", { name: /clear local history/i }),
    );

    expect(await screen.findByText("No errors yet")).toBeInTheDocument();
    expect(screen.queryByText("OOM Killed")).not.toBeInTheDocument();
  });

  it("makes a failed diagnosis retryable", async () => {
    apiMocks.createJob.mockRejectedValue(new Error("gateway unavailable"));
    addErrorQueueItem({
      source: "scenario",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });

    render(<ErrorsClient />);
    await userEvent.click(await screen.findByRole("button", { name: /^diagnose$/i }));

    expect(await screen.findByText("Diagnosis failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry diagnosis/i })).toBeInTheDocument();
    expect(loadErrorQueue()[0]?.status).toBe("diagnosis_failed");
  });

  it("resets a demo workload before marking its incident completed", async () => {
    apiMocks.resetScenarios.mockResolvedValue({ reset: true });
    const item = addErrorQueueItem({
      source: "scenario",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      status: "diagnosed",
      incidentId: "incident-1",
    });

    render(<ErrorsClient />);
    await userEvent.click(
      await screen.findByRole("button", { name: /mark as completed/i }),
    );

    await waitFor(() => expect(apiMocks.cancelActiveJobs).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.resetScenarios).toHaveBeenCalled());
    expect(loadErrorQueue().find((candidate) => candidate.id === item.id)?.status).toBe(
      "fixed",
    );
  });

  it("marks a detected incident completed without resetting the workload", async () => {
    const item = addErrorQueueItem({
      source: "detected",
      namespace: "demo",
      podName: "demo-app",
      status: "diagnosed",
      incidentId: "incident-2",
    });

    render(<ErrorsClient />);
    await userEvent.click(
      await screen.findByRole("button", { name: /mark as completed/i }),
    );

    expect(apiMocks.resetScenarios).not.toHaveBeenCalled();
    expect(loadErrorQueue().find((candidate) => candidate.id === item.id)?.status).toBe(
      "fixed",
    );
  });

  it("cancels the previous job before re-diagnosing", async () => {
    apiMocks.getJob.mockResolvedValue({
      job_id: "job-old",
      namespace: "demo",
      pod_name: "demo-app",
      target_kind: "Pod",
      status: "llm_call",
      stage: "Calling mock",
      incident_id: null,
      latency_ms: null,
      error: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    apiMocks.cancelJob.mockResolvedValue({ status: "failed" });
    apiMocks.createJob.mockResolvedValue({ job_id: "job-new", status: "queued" });
    addErrorQueueItem({
      source: "scenario",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      status: "diagnosing",
      jobId: "job-old",
    });

    render(<ErrorsClient />);
    await userEvent.click(await screen.findByRole("button", { name: /re-diagnose/i }));

    expect(apiMocks.cancelJob).toHaveBeenCalledWith("job-old");
    expect(apiMocks.createJob).toHaveBeenCalledWith({
      namespace: "demo",
      pod_name: "demo-app",
      target_kind: "Pod",
    });
    await waitFor(() =>
      expect(loadErrorQueue()[0]).toMatchObject({
        status: "diagnosing",
        jobId: "job-new",
      }),
    );
  });
});
