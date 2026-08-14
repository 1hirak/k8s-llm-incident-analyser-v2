import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppSidebar, MobileNav } from "@/components/app-sidebar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

vi.mock("@/lib/api", () => ({
  getHealth: () => Promise.resolve({ status: "ok", service: "gateway", version: "0.1", provider: "mock", model: "(none)", cluster: "connected" }),
}));

describe("AppSidebar", () => {
  it("renders brand name", async () => {
    render(<AppSidebar />);
    const brand = await screen.findByText("K8s Incident Analyser");
    expect(brand).toBeInTheDocument();
  });

  it("renders workflow nav items", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Trigger Error")).toBeInTheDocument();
    expect(screen.getByText("Errors")).toBeInTheDocument();
    expect(screen.getByText("Reports")).toBeInTheDocument();
  });

  it("renders system nav items", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText("Diagnose Target")).toBeInTheDocument();
    expect(screen.getByText("Activity")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders health pill", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText(/gateway/)).toBeInTheDocument();
  });

  it("Dashboard link points to /", async () => {
    render(<AppSidebar />);
    const link = (await screen.findByText("Dashboard")).closest("a");
    expect(link).toHaveAttribute("href", "/");
  });

  it("Trigger Error link points to /scenarios", async () => {
    render(<AppSidebar />);
    const link = screen.getByText("Trigger Error").closest("a");
    expect(link).toHaveAttribute("href", "/scenarios");
  });

  it("renders Workflow section label", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText("Workflow")).toBeInTheDocument();
  });

  it("renders System section label", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText("System")).toBeInTheDocument();
  });
});

describe("MobileNav", () => {
  it("renders brand", async () => {
    render(<MobileNav />);
    expect(await screen.findByText("K8s Incident Analyser")).toBeInTheDocument();
  });

  it("renders menu button", async () => {
    render(<MobileNav />);
    expect(await screen.findByRole("button", { name: /open menu/i })).toBeInTheDocument();
  });
});
