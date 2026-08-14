import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  createJob: () => Promise.resolve({ job_id: "job-123", status: "queued" }),
  listTargets: (kind: string) =>
    Promise.resolve({
      items:
        kind === "Namespace"
          ? [{ name: "demo", kind: "Namespace" }]
           : [{ name: "demo-app", kind }],
    }),
  getSettings: () =>
    Promise.resolve({
      provider: "mock",
      model: null,
      source: "env",
      providers: [
        { id: "mock", name: "Mock (heuristic)", model: "(none)", available: true },
      ],
    }),
  API_BASE_URL: "http://localhost:8000",
}));

vi.mock("@/lib/sse", () => ({
  streamJob: () => () => {},
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/analyse",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("AnalysePage", () => {
  it("renders page header", async () => {
    const { default: AnalysePage } = await import("@/app/analyse/page");
    render(<AnalysePage />);
    expect(await screen.findByText("Diagnose Target")).toBeInTheDocument();
  });

  it("renders target selectors", async () => {
    const { default: AnalysePage } = await import("@/app/analyse/page");
    render(<AnalysePage />);
    expect(await screen.findByLabelText("Namespace")).toBeInTheDocument();
    expect(screen.getByLabelText("Resource type")).toBeInTheDocument();
    expect(screen.getByLabelText("Resource name")).toBeInTheDocument();
  });

  it("renders submit button", async () => {
    const { default: AnalysePage } = await import("@/app/analyse/page");
    render(<AnalysePage />);
    const btn = await screen.findByRole("button", { name: /diagnose|run/i });
    expect(btn).toBeInTheDocument();
  });
});
