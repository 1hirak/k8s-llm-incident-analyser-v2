import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { STATUS } = vi.hoisted(() => ({
  STATUS: {
    provider: "mock",
    model: null,
    source: "env",
    providers: [
      { id: "mock", name: "Mock (heuristic)", model: "(none)", available: true },
      { id: "openai", name: "OpenAI", model: "gpt-4o-mini", available: false },
      { id: "anthropic", name: "Anthropic", model: "claude-haiku-4-5-20251001", available: true },
      { id: "deepseek", name: "DeepSeek", model: "deepseek-chat", available: false },
      { id: "openrouter", name: "OpenRouter", model: "openrouter/free", available: false },
    ],
  },
}));

vi.mock("@/lib/api", () => ({
  getSettings: vi.fn().mockResolvedValue(STATUS),
  saveSettings: vi.fn().mockResolvedValue({
    provider: "openai",
    model: "gpt-4o-mini",
    source: "file",
    providers: STATUS.providers.map((p) =>
      p.id === "openai" ? { ...p, available: true } : p,
    ),
  }),
  ApiError: class ApiError extends Error {},
  API_BASE_URL: "http://localhost:8000",
}));

import { saveSettings } from "@/lib/api";

describe("SettingsPage", () => {
  it("renders page title and description", async () => {
    const { default: SettingsPage } = await import("@/app/settings/page");
    render(<SettingsPage />);
    expect(await screen.findByText("Settings")).toBeInTheDocument();
    expect(
      screen.getByText(/Configure the LLM provider used for analyses/),
    ).toBeInTheDocument();
  });

  it("renders all provider cards", async () => {
    const { default: SettingsPage } = await import("@/app/settings/page");
    render(<SettingsPage />);
    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek")).toBeInTheDocument();
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
    expect(screen.getAllByText("Mock (heuristic)").length).toBeGreaterThan(0);
  });

  it("shows availability badges", async () => {
    const { default: SettingsPage } = await import("@/app/settings/page");
    render(<SettingsPage />);
    expect(await screen.findByText("Key configured")).toBeInTheDocument();
    expect(screen.getAllByText("Key needed").length).toBeGreaterThan(0);
  });

  it("marks the active provider", async () => {
    const { default: SettingsPage } = await import("@/app/settings/page");
    render(<SettingsPage />);
    expect(await screen.findByText("Active")).toBeInTheDocument();
  });

  it("selecting a provider shows its config form", async () => {
    const user = userEvent.setup();
    const { default: SettingsPage } = await import("@/app/settings/page");
    render(<SettingsPage />);
    await user.click(await screen.findByText("OpenAI"));
    expect(await screen.findByLabelText("API key")).toBeInTheDocument();
    expect(screen.getByLabelText(/Model override/)).toBeInTheDocument();
  });

  it("saving a key posts the provider config", async () => {
    const user = userEvent.setup();
    const { default: SettingsPage } = await import("@/app/settings/page");
    render(<SettingsPage />);
    await user.click(await screen.findByText("OpenAI"));
    const keyInput = await screen.findByLabelText("API key");
    await user.type(keyInput, "sk-secret");
    await user.click(screen.getByRole("button", { name: /Save/ }));
    expect(saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: "openai",
        api_key: "sk-secret",
      }),
    );
  });
});
