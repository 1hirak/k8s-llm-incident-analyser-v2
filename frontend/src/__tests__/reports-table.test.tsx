import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportsTable } from "@/components/reports-table";
import type { ReportSummary } from "@/types";

const mockReport: ReportSummary = {
  incident_id: "019f8787-9609-7ec2-9420-0c1119f3d5ca",
  namespace: "demo",
  pod_name: "demo-app-abc",
  failure_category: "crash",
  severity: "high",
  confidence: 0.85,
  incident_summary: "Pod crashed due to OOMKilled",
  created_at: "2026-07-22T10:00:00Z",
};

describe("ReportsTable", () => {
  it("renders column headers", () => {
    render(<ReportsTable reports={[mockReport]} />);
    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText("Severity")).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
    expect(screen.getByText("Target")).toBeInTheDocument();
    expect(screen.getByText("Created")).toBeInTheDocument();
  });

  it("renders report row", () => {
    render(<ReportsTable reports={[mockReport]} />);
    expect(screen.getByText("Pod crashed due to OOMKilled")).toBeInTheDocument();
    expect(screen.getByText("crash")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("renders link to report detail", () => {
    render(<ReportsTable reports={[mockReport]} />);
    const link = screen.getByText("Pod crashed due to OOMKilled").closest("a");
    expect(link).toHaveAttribute("href", "/reports/019f8787-9609-7ec2-9420-0c1119f3d5ca");
  });

  it("renders short ID", () => {
    render(<ReportsTable reports={[mockReport]} />);
    expect(screen.getByText("019f8787")).toBeInTheDocument();
  });

  it("renders namespace/pod target", () => {
    render(<ReportsTable reports={[mockReport]} />);
    expect(screen.getByText("demo/demo-app-abc")).toBeInTheDocument();
  });

  it("renders multiple rows", () => {
    const reports = [mockReport, { ...mockReport, incident_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" }];
    render(<ReportsTable reports={reports} />);
    expect(screen.getAllByText("crash")).toHaveLength(2);
  });

  it("renders empty table body when no reports", () => {
    const { container } = render(<ReportsTable reports={[]} />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(0);
  });
});
