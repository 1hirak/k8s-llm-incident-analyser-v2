import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import RootLayout from "@/app/layout";

vi.mock("@/components/app-sidebar", () => ({
  AppSidebar: () => <aside data-testid="sidebar">Sidebar</aside>,
  MobileNav: () => <nav data-testid="mobile-nav">MobileNav</nav>,
}));

vi.mock("@/components/ui/sonner", () => ({
  Toaster: () => <div data-testid="toaster">Toaster</div>,
}));

vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-inter" }),
}));

describe("RootLayout", () => {
  it("renders sidebar", async () => {
    const jsx = await RootLayout({ children: <p>child</p> });
    render(jsx);
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
  });

  it("renders mobile nav", async () => {
    const jsx = await RootLayout({ children: <p>child</p> });
    render(jsx);
    expect(screen.getByTestId("mobile-nav")).toBeInTheDocument();
  });

  it("renders children", async () => {
    const jsx = await RootLayout({ children: <p>Custom child</p> });
    render(jsx);
    expect(screen.getByText("Custom child")).toBeInTheDocument();
  });

  it("renders toaster", async () => {
    const jsx = await RootLayout({ children: <div /> });
    render(jsx);
    expect(screen.getByTestId("toaster")).toBeInTheDocument();
  });

  it("has dark class on html", async () => {
    const jsx = await RootLayout({ children: <div /> });
    render(jsx);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
