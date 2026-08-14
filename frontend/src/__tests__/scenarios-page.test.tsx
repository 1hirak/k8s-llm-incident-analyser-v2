import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clearErrorQueue, loadErrorQueue } from "@/lib/error-queue";

const applyScenario = vi.fn();

vi.mock("@/lib/api", () => ({
  listScenarios: () => Promise.resolve({
    items: [
      { scenario_id: "01-missing-env", name: "Missing Env", category: "config", description: "DATABASE_URL empty", severity: "critical" },
      { scenario_id: "05-oom", name: "OOM Killed", category: "resource", description: "Memory limit 32Mi", severity: "high" },
    ],
  }),
  applyScenario: (...args: unknown[]) => applyScenario(...args),
  cancelActiveJobs: () => Promise.resolve({ cancelled: 0 }),
  resetScenarios: () => Promise.resolve({ reset: true }),
  API_BASE_URL: "http://localhost:8000",
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/scenarios",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("ScenariosPage", () => {
  beforeEach(() => {
    clearErrorQueue();
    applyScenario.mockReset();
  });

  it("renders page title", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    expect(await screen.findByText("Trigger an Error")).toBeInTheDocument();
  });

  it("renders scenario cards", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    expect(await screen.findByText("Missing Env")).toBeInTheDocument();
    expect(screen.getByText("OOM Killed")).toBeInTheDocument();
  });

  it("renders Trigger Error buttons", async () => {
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);
    const buttons = await screen.findAllByText("Trigger Error");
    expect(buttons).toHaveLength(2);
  });

  it("creates an error queue record when triggering a scenario", async () => {
    applyScenario.mockResolvedValue({ applied: true, scenario_id: "05-oom", fault_description: "OOM" });
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);

    const buttons = await screen.findAllByText("Trigger Error");
    await userEvent.click(buttons[1]);

    expect(screen.getByText(/trigger.*oom killed/i)).toBeInTheDocument();
    const confirmButtons = screen.getAllByRole("button", { name: /^trigger error$/i });
    await userEvent.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(applyScenario).toHaveBeenCalledWith("05-oom"));
    await waitFor(() => expect(loadErrorQueue()).toHaveLength(1));
    expect(loadErrorQueue()[0]?.scenarioName).toBe("OOM Killed");
  });

  it("allows a second scenario while the first is active", async () => {
    applyScenario.mockResolvedValue({ applied: true, fault_description: "fault" });
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);

    const buttons = await screen.findAllByText("Trigger Error");
    await userEvent.click(buttons[0]);
    await userEvent.click(screen.getAllByRole("button", { name: /^trigger error$/i }).at(-1)!);
    await waitFor(() => expect(loadErrorQueue()).toHaveLength(1));

    await userEvent.click(screen.getAllByText("Trigger Error")[1]);
    await userEvent.click(screen.getAllByRole("button", { name: /^trigger error$/i }).at(-1)!);
    await waitFor(() => expect(loadErrorQueue()).toHaveLength(2));
    expect(applyScenario).toHaveBeenCalledTimes(2);
  });

  it("resets the workload so the same scenario can be triggered again", async () => {
    applyScenario.mockResolvedValue({ applied: true, fault_description: "fault" });
    const { default: ScenariosPage } = await import("@/app/scenarios/page");
    render(<ScenariosPage />);

    await userEvent.click((await screen.findAllByText("Trigger Error"))[1]);
    await userEvent.click(
      screen.getAllByRole("button", { name: /^trigger error$/i }).at(-1)!,
    );
    await waitFor(() => expect(loadErrorQueue()).toHaveLength(1));

    await userEvent.click(screen.getByRole("button", { name: /reset demo/i }));
    await waitFor(() =>
      expect(loadErrorQueue()[0]?.status).toBe("fixed"),
    );

    await userEvent.click(screen.getAllByText("Trigger Error")[1]);
    await userEvent.click(
      screen.getAllByRole("button", { name: /^trigger error$/i }).at(-1)!,
    );
    await waitFor(() => expect(applyScenario).toHaveBeenCalledTimes(2));
  });
});
