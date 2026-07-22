import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  listScenarios: () => Promise.resolve({
    items: [
      { scenario_id: "01-missing-env", name: "Missing Env", category: "config", description: "DATABASE_URL empty", severity: "critical" },
      { scenario_id: "05-oom", name: "OOM Killed", category: "resource", description: "Memory limit 32Mi", severity: "high" },
    ],
  }),
  applyScenario: () => Promise.resolve({ applied: true, scenario_id: "05-oom", fault_description: "OOM" }),
  resetScenarios: () => Promise.resolve({ reset: true }),
  API_BASE_URL: "http://localhost:8000",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/scenarios",
  useRouter: () => ({ refresh: vi.fn() }),
}));

describe("ScenariosPage", () => {
  it("renders page title", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    expect(await screen.findByText("Scenarios")).toBeInTheDocument();
  });

  it("renders scenario cards", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    expect(await screen.findByText("Missing Env")).toBeInTheDocument();
    expect(screen.getByText("OOM Killed")).toBeInTheDocument();
  });

  it("renders Apply buttons", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    const buttons = await screen.findAllByText("Apply");
    expect(buttons).toHaveLength(2);
  });

  it("renders Reset cluster button", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    expect(await screen.findByText("Reset cluster")).toBeInTheDocument();
  });
});
