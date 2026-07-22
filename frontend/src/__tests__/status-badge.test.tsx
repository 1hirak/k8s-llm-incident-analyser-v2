import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { JobStatusBadge, SeverityBadge, CategoryBadge } from "@/components/status-badge";
import type { JobStatus, Severity, FailureCategory } from "@/types";

describe("JobStatusBadge", () => {
  it("renders queued", () => {
    render(<JobStatusBadge status="queued" />);
    expect(screen.getByText("Queued")).toBeInTheDocument();
  });

  it("renders collecting", () => {
    render(<JobStatusBadge status="collecting" />);
    expect(screen.getByText("Collecting")).toBeInTheDocument();
  });

  it("renders processing", () => {
    render(<JobStatusBadge status="processing" />);
    expect(screen.getByText("Processing")).toBeInTheDocument();
  });

  it("renders llm_call", () => {
    render(<JobStatusBadge status="llm_call" />);
    expect(screen.getByText("LLM call")).toBeInTheDocument();
  });

  it("renders persisting", () => {
    render(<JobStatusBadge status="persisting" />);
    expect(screen.getByText("Persisting")).toBeInTheDocument();
  });

  it("renders done", () => {
    render(<JobStatusBadge status="done" />);
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("renders failed", () => {
    render(<JobStatusBadge status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<JobStatusBadge status="done" className="custom" />);
    expect(container.querySelector(".custom")).toBeInTheDocument();
  });
});

describe("SeverityBadge", () => {
  it("renders low", () => {
    render(<SeverityBadge severity="low" />);
    expect(screen.getByText("low")).toBeInTheDocument();
  });

  it("renders medium", () => {
    render(<SeverityBadge severity="medium" />);
    expect(screen.getByText("medium")).toBeInTheDocument();
  });

  it("renders high", () => {
    render(<SeverityBadge severity="high" />);
    expect(screen.getByText("high")).toBeInTheDocument();
  });

  it("renders critical", () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<SeverityBadge severity="critical" className="custom" />);
    expect(container.querySelector(".custom")).toBeInTheDocument();
  });
});

describe("CategoryBadge", () => {
  it("renders crash", () => {
    render(<CategoryBadge category="crash" />);
    expect(screen.getByText("crash")).toBeInTheDocument();
  });

  it("renders config", () => {
    render(<CategoryBadge category="config" />);
    expect(screen.getByText("config")).toBeInTheDocument();
  });

  it("renders dependency", () => {
    render(<CategoryBadge category="dependency" />);
    expect(screen.getByText("dependency")).toBeInTheDocument();
  });

  it("renders network", () => {
    render(<CategoryBadge category="network" />);
    expect(screen.getByText("network")).toBeInTheDocument();
  });

  it("renders image", () => {
    render(<CategoryBadge category="image" />);
    expect(screen.getByText("image")).toBeInTheDocument();
  });

  it("renders resource", () => {
    render(<CategoryBadge category="resource" />);
    expect(screen.getByText("resource")).toBeInTheDocument();
  });

  it("renders probe", () => {
    render(<CategoryBadge category="probe" />);
    expect(screen.getByText("probe")).toBeInTheDocument();
  });

  it("renders unknown", () => {
    render(<CategoryBadge category="unknown" />);
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });
});
