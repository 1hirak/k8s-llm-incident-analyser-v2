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

  it("renders all nav items", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Analyse")).toBeInTheDocument();
    expect(screen.getByText("Jobs")).toBeInTheDocument();
    expect(screen.getByText("Reports")).toBeInTheDocument();
    expect(screen.getByText("Scenarios")).toBeInTheDocument();
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

  it("Analyse link points to /analyse", async () => {
    render(<AppSidebar />);
    const link = screen.getByText("Analyse").closest("a");
    expect(link).toHaveAttribute("href", "/analyse");
  });

  it("renders Console section label", async () => {
    render(<AppSidebar />);
    expect(await screen.findByText("Console")).toBeInTheDocument();
  });
});

describe("MobileNav", () => {
  it("renders brand", async () => {
    render(<MobileNav />);
    expect(await screen.findByText("K8s Incident Analyser")).toBeInTheDocument();
  });

  it("renders all nav links", async () => {
    render(<MobileNav />);
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
  });
});
