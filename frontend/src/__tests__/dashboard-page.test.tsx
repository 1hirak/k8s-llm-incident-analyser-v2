import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DashboardLoading from "@/app/loading";

describe("DashboardPage", () => {
  it("renders loading skeleton page", () => {
    const { container } = render(<DashboardLoading />);
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });
});
