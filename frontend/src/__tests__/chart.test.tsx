import { describe, it, expect, beforeAll } from "vitest";
import { render } from "@testing-library/react";

beforeAll(() => {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverMock;
});

describe("CategoryChart", () => {
  it("renders without crashing with data", async () => {
    const { CategoryChart } = await import("@/components/category-chart");
    const { container } = render(<CategoryChart data={[{ category: "crash", count: 5 }]} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("renders without crashing with empty data", async () => {
    const { CategoryChart } = await import("@/components/category-chart");
    const { container } = render(<CategoryChart data={[]} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });
});

describe("LatencyChart", () => {
  it("renders without crashing with data", async () => {
    const { LatencyChart } = await import("@/components/latency-chart");
    const { container } = render(<LatencyChart data={[{ label: "07-22", latency_ms: 500 }]} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("renders without crashing with empty data", async () => {
    const { LatencyChart } = await import("@/components/latency-chart");
    const { container } = render(<LatencyChart data={[]} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });
});
