import { describe, it, expect, beforeEach } from "vitest";
import {
  addErrorQueueItem,
  clearErrorQueue,
  getActiveScenarioError,
  getErrorQueueItem,
  hasActiveScenarioError,
  loadErrorQueue,
  markAllActiveScenarioErrorsFixed,
  updateErrorQueueItem,
} from "@/lib/error-queue";

describe("error queue", () => {
  beforeEach(() => {
    clearErrorQueue();
  });

  it("starts empty", () => {
    expect(loadErrorQueue()).toEqual([]);
  });

  it("adds a scenario error", () => {
    const item = addErrorQueueItem({
      source: "scenario",
      scenarioId: "05-oom",
      scenarioName: "OOM Killed",
      namespace: "demo",
      podName: "demo-app",
      category: "resource",
      severity: "high",
      status: "triggered",
    });
    expect(item.id).toBeDefined();
    expect(item.status).toBe("triggered");
    expect(loadErrorQueue()).toHaveLength(1);
  });

  it("updates an item", () => {
    const item = addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    const updated = updateErrorQueueItem(item.id, {
      status: "diagnosed",
      incidentId: "inc-1",
    });
    expect(updated?.status).toBe("diagnosed");
    expect(updated?.incidentId).toBe("inc-1");
    expect(getErrorQueueItem(item.id)?.status).toBe("diagnosed");
  });

  it("persists a diagnosis failure for a later retry", () => {
    const item = addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "diagnosing",
      jobId: "job-1",
    });

    updateErrorQueueItem(item.id, {
      status: "diagnosis_failed",
      diagnosisError: "The diagnosis job timed out.",
    });

    expect(loadErrorQueue()[0]).toMatchObject({
      status: "diagnosis_failed",
      diagnosisError: "The diagnosis job timed out.",
    });
  });

  it("returns null when updating unknown item", () => {
    expect(updateErrorQueueItem("missing", { status: "fixed" })).toBeNull();
  });

  it("detects active scenario error", () => {
    addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    expect(hasActiveScenarioError()).toBe(true);
    expect(getActiveScenarioError()).not.toBeNull();
  });

  it("does not treat fixed scenario as active", () => {
    const item = addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    updateErrorQueueItem(item.id, { status: "fixed" });
    expect(hasActiveScenarioError()).toBe(false);
    expect(getActiveScenarioError()).toBeNull();
  });

  it("does not treat detected errors as active scenario errors", () => {
    addErrorQueueItem({
      source: "detected",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    expect(hasActiveScenarioError()).toBe(false);
  });

  it("marks all active scenario errors fixed together", () => {
    addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "diagnosed",
    });
    addErrorQueueItem({
      source: "scenario",
      namespace: "demo",
      podName: "demo-app",
      status: "fixed",
    });

    expect(markAllActiveScenarioErrorsFixed()).toBe(2);
    expect(loadErrorQueue().every((item) => item.status === "fixed")).toBe(true);
  });

  it("ignores malformed persisted records", () => {
    localStorage.setItem(
      "k8s-incident-analyser.error-queue.v1",
      JSON.stringify([{ invalid: true }]),
    );
    expect(loadErrorQueue()).toEqual([]);
  });

  it("survives a round-trip", () => {
    addErrorQueueItem({
      source: "scenario",
      scenarioName: "Crash",
      namespace: "demo",
      podName: "demo-app",
      status: "triggered",
    });
    const reloaded = loadErrorQueue();
    expect(reloaded).toHaveLength(1);
    expect(reloaded[0]?.scenarioName).toBe("Crash");
  });
});
