import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  createJob: () => Promise.resolve({ job_id: "job-123", status: "queued" }),
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
    expect(await screen.findByText("Analyse")).toBeInTheDocument();
  });

  it("renders input fields", async () => {
    const { default: AnalysePage } = await import("@/app/analyse/page");
    render(<AnalysePage />);
    expect(await screen.findByLabelText("Namespace")).toBeInTheDocument();
    expect(screen.getByLabelText("Pod name")).toBeInTheDocument();
  });

  it("renders submit button", async () => {
    const { default: AnalysePage } = await import("@/app/analyse/page");
    render(<AnalysePage />);
    const btn = await screen.findByRole("button", { name: /analyse|run/i });
    expect(btn).toBeInTheDocument();
  });
});
