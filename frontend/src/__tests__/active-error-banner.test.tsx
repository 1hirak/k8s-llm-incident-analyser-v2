import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActiveErrorBanner } from "@/components/active-error-banner";
import type { ErrorQueueItem } from "@/types";

const baseItem: ErrorQueueItem = {
  id: "err-1",
  source: "scenario",
  scenarioName: "OOM Killed",
  namespace: "demo",
  podName: "demo-app",
  category: "resource",
  severity: "high",
  triggeredAt: new Date().toISOString(),
  status: "triggered",
};

describe("ActiveErrorBanner", () => {
  it("renders active error details", () => {
    render(<ActiveErrorBanner errors={[baseItem]} />);
    expect(screen.getByText("Active simulated error")).toBeInTheDocument();
    expect(screen.getByText("OOM Killed")).toBeInTheDocument();
    expect(screen.getByText("demo/demo-app")).toBeInTheDocument();
    expect(screen.getByText("Needs diagnosis")).toBeInTheDocument();
  });

  it("links to the error queue", () => {
    render(<ActiveErrorBanner errors={[baseItem]} />);
    expect(screen.getByRole("link", { name: /open error queue/i })).toHaveAttribute(
      "href",
      "/errors",
    );
  });

  it("summarizes multiple active errors", () => {
    const second: ErrorQueueItem = {
      ...baseItem,
      id: "err-2",
      scenarioName: "DB Unavailable",
      category: "dependency",
    };
    render(<ActiveErrorBanner errors={[baseItem, second]} />);
    expect(screen.getByText("2 active simulated errors")).toBeInTheDocument();
    expect(screen.getByText("OOM Killed")).toBeInTheDocument();
    expect(screen.getByText("DB Unavailable")).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });
});
