import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/empty-state";
import { ConfidenceMeter } from "@/components/confidence-meter";
import { CopyButton } from "@/components/copy-button";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { Box } from "lucide-react";

describe("EmptyState", () => {
  it("renders title", () => {
    render(<EmptyState title="No data" />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
  it("renders description when provided", () => {
    render(<EmptyState title="No data" description="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
  it("does not render description when absent", () => {
    const { container } = render(<EmptyState title="No data" />);
    expect(container.querySelector(".max-w-md")).not.toBeInTheDocument();
  });
  it("renders children", () => {
    render(<EmptyState title="No data"><button type="button">Action</button></EmptyState>);
    expect(screen.getByText("Action")).toBeInTheDocument();
  });
  it("renders icon", () => {
    render(<EmptyState title="No data" icon={Box} />);
    expect(document.querySelector(".lucide-box")).toBeInTheDocument();
  });
  it("no icon when not provided", () => {
    render(<EmptyState title="No data" />);
    expect(document.querySelector(".lucide-box")).not.toBeInTheDocument();
  });
});

describe("ConfidenceMeter", () => {
  it("0.85 → 85%", () => {
    render(<ConfidenceMeter value={0.85} />);
    expect(screen.getByText("85%")).toBeInTheDocument();
  });
  it("0 → 0%", () => {
    render(<ConfidenceMeter value={0} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
  it("1.0 → 100%", () => {
    render(<ConfidenceMeter value={1.0} />);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });
  it("clamps negative to 0%", () => {
    render(<ConfidenceMeter value={-0.5} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
  it("clamps above 1 to 100%", () => {
    render(<ConfidenceMeter value={1.5} />);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });
  it("hides label when showLabel=false", () => {
    render(<ConfidenceMeter value={0.5} showLabel={false} />);
    expect(screen.queryByText("50%")).not.toBeInTheDocument();
  });
});

describe("CopyButton", () => {
  it("renders copy icon", () => {
    render(<CopyButton text="hello" />);
    expect(screen.getByLabelText("Copy to clipboard")).toBeInTheDocument();
    expect(document.querySelector(".lucide-copy")).toBeInTheDocument();
  });
  it("is a button", () => {
    render(<CopyButton text="hello" />);
    expect(screen.getByLabelText("Copy to clipboard").tagName).toBe("BUTTON");
  });
});

describe("PageHeader", () => {
  it("renders title", () => {
    render(<PageHeader title="Dashboard" />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });
  it("renders description", () => {
    render(<PageHeader title="Dash" description="Overview" />);
    expect(screen.getByText("Overview")).toBeInTheDocument();
  });
  it("renders kicker", () => {
    render(<PageHeader kicker="OVR" title="Dash" />);
    expect(screen.getByText("OVR")).toBeInTheDocument();
  });
  it("renders children", () => {
    render(<PageHeader title="Dash"><button type="button">Refresh</button></PageHeader>);
    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });
  it("no optional fields when absent", () => {
    const { container } = render(<PageHeader title="Dash" />);
    expect(container.querySelector(".max-w-prose")).not.toBeInTheDocument();
  });
});

describe("StatCard", () => {
  it("renders title and value", () => {
    render(<StatCard title="Total" value="42" />);
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });
  it("renders hint", () => {
    render(<StatCard title="Total" value="42" hint="Last 7d" />);
    expect(screen.getByText("Last 7d")).toBeInTheDocument();
  });
  it("renders icon", () => {
    render(<StatCard title="Total" value="42" icon={Box} />);
    expect(document.querySelector(".lucide-box")).toBeInTheDocument();
  });
  it("no hint when absent", () => {
    const { container } = render(<StatCard title="Total" value="42" />);
    expect(container.querySelector(".mt-1")).not.toBeInTheDocument();
  });
});
