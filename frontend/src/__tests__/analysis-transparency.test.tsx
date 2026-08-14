import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AnalysisTransparency } from "@/components/analysis-transparency";

const explanation = {
  rationale: "The process is restarting because Kubernetes killed it after memory exhaustion.",
  key_signals: ["Evidence includes OOMKilled.", "The target has restarted 3 time(s)."],
  uncertainty: "Confirm the memory limit and inspect the workload's recent traffic.",
  input_summary: {
    current_log_lines: 4,
    previous_log_lines: 2,
    has_pod_status: true,
    has_kubernetes_events: true,
    restart_count: 3,
    related_pod_count: 1,
    redaction_applied: true,
    redaction_count: 2,
  },
};

describe("AnalysisTransparency", () => {
  it("renders the explanation, signals, uncertainty, and input provenance", () => {
    render(
      <AnalysisTransparency
        explanation={explanation}
        providerName="DeepSeek"
        model="deepseek-chat"
      />,
    );

    expect(screen.getByText("How this diagnosis was formed")).toBeInTheDocument();
    expect(screen.getByText(explanation.rationale)).toBeInTheDocument();
    expect(screen.getByText("Evidence includes OOMKilled.")).toBeInTheDocument();
    expect(screen.getByText(explanation.uncertainty)).toBeInTheDocument();
    expect(screen.getByText("4 current · 2 previous")).toBeInTheDocument();
    expect(screen.getByText("2 value(s) redacted")).toBeInTheDocument();
    expect(screen.getByText("Provider: DeepSeek")).toBeInTheDocument();
  });

  it("explains why older reports have less detail", () => {
    render(<AnalysisTransparency />);

    expect(
      screen.getByText(/created before structured transparency data was available/i),
    ).toBeInTheDocument();
  });
});
