import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  listReports: () => Promise.resolve({
    items: [{
      incident_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", namespace: "demo", pod_name: "p",
      failure_category: "crash", severity: "high", confidence: 0.85,
      incident_summary: "Pod crashed", created_at: "2026-07-22T10:00:00Z",
    }],
    count: 1, limit: 20, offset: 0,
  }),
  API_BASE_URL: "http://localhost:8000",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/reports",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("ReportsPage", () => {
  it("renders page header", async () => {
    const { default: ReportsPage } = await import("@/app/reports/page");
    render(<ReportsPage />);
    expect(await screen.findByText("Reports")).toBeInTheDocument();
  });

  it("renders report data", async () => {
    const { default: ReportsPage } = await import("@/app/reports/page");
    render(<ReportsPage />);
    expect(await screen.findByText("Pod crashed")).toBeInTheDocument();
  });
});
