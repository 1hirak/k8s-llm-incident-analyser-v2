import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  listJobs: () => Promise.resolve({
    items: [{
      job_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", namespace: "demo", pod_name: "demo-app",
      status: "done", stage: null, incident_id: "iiiiiiii-iiii-iiii-iiii-iiiiiiiiiiii",
      latency_ms: 1234, error: null, created_at: "2026-07-22T10:00:00Z", updated_at: "2026-07-22T10:01:00Z",
    }],
    count: 1, limit: 15, offset: 0,
  }),
  API_BASE_URL: "http://localhost:8000",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/jobs",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("JobsPage", () => {
  it("renders page header", async () => {
    const { default: JobsPage } = await import("@/app/jobs/page");
    render(<JobsPage />);
    expect(await screen.findByText("Activity")).toBeInTheDocument();
  });

  it("renders job row", async () => {
    const { default: JobsPage } = await import("@/app/jobs/page");
    render(<JobsPage />);
    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(screen.getByText("demo/demo-app")).toBeInTheDocument();
  });
});
