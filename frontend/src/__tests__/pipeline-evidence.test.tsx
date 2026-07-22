import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineTimeline } from "@/components/pipeline-timeline";
import { EvidenceCard } from "@/components/evidence-card";
import type { EvidenceItem } from "@/types";

describe("PipelineTimeline", () => {
  it("renders all 6 stage labels", () => {
    render(<PipelineTimeline status="queued" />);
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Collecting")).toBeInTheDocument();
    expect(screen.getByText("Processing")).toBeInTheDocument();
    expect(screen.getByText("LLM call")).toBeInTheDocument();
    expect(screen.getByText("Persisting")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("shows checks for completed stages on done", () => {
    const { container } = render(<PipelineTimeline status="done" />);
    expect(container.querySelectorAll(".lucide-check").length).toBeGreaterThanOrEqual(5);
  });

  it("shows loader on active stage", () => {
    const { container } = render(<PipelineTimeline status="collecting" />);
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("shows X on failed stage", () => {
    const { container } = render(<PipelineTimeline status="persisting" failed />);
    expect(container.querySelectorAll(".lucide-x").length).toBeGreaterThanOrEqual(1);
  });

  it("shows custom stage description when provided", () => {
    render(<PipelineTimeline status="llm_call" stage="Calling OpenAI gpt-4o" />);
    expect(screen.getByText("Calling OpenAI gpt-4o")).toBeInTheDocument();
  });

  it("shows default description for non-current stage", () => {
    render(<PipelineTimeline status="queued" />);
    expect(screen.getByText("Job accepted and waiting to run")).toBeInTheDocument();
  });

  it("shows circle for future stages", () => {
    const { container } = render(<PipelineTimeline status="collecting" />);
    expect(container.querySelectorAll(".lucide-circle").length).toBeGreaterThanOrEqual(1);
  });
});

describe("EvidenceCard", () => {
  const evidence: EvidenceItem = {
    source: "pod_log",
    pod: "demo-app-abc123",
    timestamp: "2026-07-22T10:00:00Z",
    evidence: "ERROR: Database connection failed",
  };

  it("renders source label", () => {
    render(<EvidenceCard item={evidence} />);
    expect(screen.getByText("Pod log")).toBeInTheDocument();
  });

  it("renders pod name", () => {
    render(<EvidenceCard item={evidence} />);
    expect(screen.getByText("demo-app-abc123")).toBeInTheDocument();
  });

  it("renders evidence content", () => {
    render(<EvidenceCard item={evidence} />);
    expect(screen.getByText("ERROR: Database connection failed")).toBeInTheDocument();
  });

  it("renders formatted timestamp", () => {
    render(<EvidenceCard item={evidence} />);
    expect(screen.getByText(/2026-07-22/)).toBeInTheDocument();
  });

  it("renders previous_pod_log label", () => {
    render(<EvidenceCard item={{ ...evidence, source: "previous_pod_log" }} />);
    expect(screen.getByText("Previous pod log")).toBeInTheDocument();
  });

  it("renders kubernetes_event label", () => {
    render(<EvidenceCard item={{ ...evidence, source: "kubernetes_event" }} />);
    expect(screen.getByText("Kubernetes event")).toBeInTheDocument();
  });

  it("renders pod_status label", () => {
    render(<EvidenceCard item={{ ...evidence, source: "pod_status" }} />);
    expect(screen.getByText("Pod status")).toBeInTheDocument();
  });

  it("hides timestamp when not provided", () => {
    const ev: EvidenceItem = { source: "pod_log", pod: "p", evidence: "e" };
    render(<EvidenceCard item={ev} />);
    expect(screen.queryByText(/UTC/)).not.toBeInTheDocument();
  });
});
