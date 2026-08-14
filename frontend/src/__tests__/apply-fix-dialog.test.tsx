import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApplyFixDialog } from "@/components/apply-fix-dialog";
import { clearErrorQueue } from "@/lib/error-queue";
import type { ErrorQueueItem, IncidentReport } from "@/types";

vi.mock("@/lib/api", () => ({
  resetScenarios: vi.fn(),
}));

const { resetScenarios } = await import("@/lib/api");

const scenarioItem: ErrorQueueItem = {
  id: "err-1",
  source: "scenario",
  scenarioName: "OOM Killed",
  namespace: "demo",
  podName: "demo-app",
  category: "resource",
  severity: "high",
  triggeredAt: new Date().toISOString(),
  status: "diagnosed",
  incidentId: "inc-1",
};

const detectedItem: ErrorQueueItem = {
  ...scenarioItem,
  source: "detected",
  scenarioName: undefined,
};

const report: IncidentReport = {
  incident_id: "inc-1",
  incident_summary: "Pod ran out of memory",
  likely_root_cause: "Memory limit too low",
  affected_component: "demo-app",
  failure_category: "resource",
  severity: "high",
  confidence: 0.9,
  supporting_evidence: [],
  suggested_fix: "Increase memory limit",
  recommended_commands: ["kubectl patch deployment demo-app -n demo"],
  human_verification_steps: ["Check pod status"],
  created_at: new Date().toISOString(),
};

describe("ApplyFixDialog", () => {
  beforeEach(() => {
    clearErrorQueue();
    vi.resetAllMocks();
  });

  it("renders review state for demo incident", () => {
    render(
      <ApplyFixDialog
        item={scenarioItem}
        report={report}
        open={true}
        onOpenChange={() => {}}
        onFixed={() => {}}
      />,
    );
    expect(screen.getByText("Apply recommended fix?")).toBeInTheDocument();
    expect(
      screen.getByText(/fault-injection system/i),
    ).toBeInTheDocument();
  });

  it("calls resetScenarios and marks fixed for demo incident", async () => {
    (resetScenarios as ReturnType<typeof vi.fn>).mockResolvedValue({ reset: true });
    const onFixed = vi.fn();

    render(
      <ApplyFixDialog
        item={scenarioItem}
        report={report}
        open={true}
        onOpenChange={() => {}}
        onFixed={onFixed}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /apply fix/i }));
    await waitFor(() => expect(resetScenarios).toHaveBeenCalled());
    await waitFor(() => expect(onFixed).toHaveBeenCalled());
  });

  it("does not call resetScenarios for detected incident", async () => {
    render(
      <ApplyFixDialog
        item={detectedItem}
        report={report}
        open={true}
        onOpenChange={() => {}}
        onFixed={() => {}}
      />,
    );

    expect(
      screen.getByRole("button", { name: /i applied the fix/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^apply fix$/i }),
    ).not.toBeInTheDocument();
  });
});
