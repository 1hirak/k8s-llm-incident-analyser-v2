import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SpotlightCard } from "@/components/spotlight-card";

describe("SpotlightCard", () => {
  it("renders children", () => {
    render(<SpotlightCard><p>Hello world</p></SpotlightCard>);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders card element", () => {
    const { container } = render(<SpotlightCard>content</SpotlightCard>);
    expect(container.querySelector(".rounded-2xl")).toBeTruthy();
  });

  it("applies className", () => {
    const { container } = render(<SpotlightCard className="custom">content</SpotlightCard>);
    const card = container.querySelector(".custom");
    expect(card).toBeInTheDocument();
  });

  it("renders glow layer", () => {
    const { container } = render(<SpotlightCard>content</SpotlightCard>);
    const glow = container.querySelector('[aria-hidden="true"]');
    expect(glow).toBeInTheDocument();
  });
});
