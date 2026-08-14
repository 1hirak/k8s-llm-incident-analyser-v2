import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ErrorCard } from "@/components/error-card";
import type { ErrorQueueItem } from "@/types";

const item: ErrorQueueItem = {
  id: "error-1",
  source: "scenario",
  scenarioName: "OOM Killed",
  namespace: "demo",
  podName: "demo-app",
  triggeredAt: new Date().toISOString(),
  status: "diagnosing",
  jobId: "job-1",
};

describe("ErrorCard", () => {
  it("allows a diagnosing item to be re-diagnosed", async () => {
    const onStartDiagnosis = vi.fn();
    render(<ErrorCard item={item} onStartDiagnosis={onStartDiagnosis} />);

    await userEvent.click(screen.getByRole("button", { name: /re-diagnose/i }));

    expect(onStartDiagnosis).toHaveBeenCalledWith(item);
  });

  it("allows a diagnosed item to be marked as completed", async () => {
    const onMarkCompleted = vi.fn();
    const diagnosedItem: ErrorQueueItem = {
      ...item,
      status: "diagnosed",
      incidentId: "incident-1",
    };
    render(
      <ErrorCard
        item={diagnosedItem}
        onMarkCompleted={onMarkCompleted}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /mark as completed/i }),
    );

    expect(onMarkCompleted).toHaveBeenCalledWith(diagnosedItem);
  });
});
