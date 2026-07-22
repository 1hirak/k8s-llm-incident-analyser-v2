import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import DashboardLoading from "@/app/loading";

describe("DashboardLoading", () => {
  it("renders skeletons", () => {
    const { container } = render(<DashboardLoading />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThanOrEqual(7);
  });
});

describe("not-found page", () => {
  it("renders 404", async () => {
    const NotFound = (await import("@/app/not-found")).default;
    render(<NotFound />);
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByText(/Page not found/)).toBeInTheDocument();
  });
});
