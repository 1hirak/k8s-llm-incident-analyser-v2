import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WorkflowStepper } from "@/components/workflow-stepper";

describe("WorkflowStepper", () => {
  it("renders three workflow steps", () => {
    render(
      <WorkflowStepper
        activeStep="trigger"
        needsDiagnosisCount={0}
        readyToFixCount={0}
      />,
    );
    expect(screen.getByText("Trigger an error")).toBeInTheDocument();
    expect(screen.getByText("Diagnose the error")).toBeInTheDocument();
    expect(screen.getByText("Apply a fix")).toBeInTheDocument();
  });

  it("shows diagnosis count", () => {
    render(
      <WorkflowStepper
        activeStep="diagnose"
        needsDiagnosisCount={2}
        readyToFixCount={0}
      />,
    );
    expect(screen.getByText("2 errors waiting for diagnosis.")).toBeInTheDocument();
  });

  it("shows ready to fix count", () => {
    render(
      <WorkflowStepper
        activeStep="fix"
        needsDiagnosisCount={0}
        readyToFixCount={1}
      />,
    );
    expect(
      screen.getByText("1 diagnosed incident ready for remediation."),
    ).toBeInTheDocument();
  });

  it("links trigger step to scenarios", () => {
    render(
      <WorkflowStepper
        activeStep="trigger"
        needsDiagnosisCount={0}
        readyToFixCount={0}
      />,
    );
    const link = screen.getByRole("link", { name: /trigger error/i });
    expect(link).toHaveAttribute("href", "/scenarios");
  });

  it("links diagnose step to errors", () => {
    render(
      <WorkflowStepper
        activeStep="diagnose"
        needsDiagnosisCount={1}
        readyToFixCount={0}
      />,
    );
    const link = screen.getByRole("link", { name: /view errors/i });
    expect(link).toHaveAttribute("href", "/errors");
  });
});
