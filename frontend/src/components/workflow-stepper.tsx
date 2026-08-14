import Link from "next/link";
import { Activity, Check, LoaderCircle, Wrench, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ErrorQueueItem } from "@/types";

export type WorkflowStep =
  | "trigger"
  | "diagnose"
  | "fix";

export function WorkflowStepper({
  activeStep,
  needsDiagnosisCount,
  readyToFixCount,
  activeError,
}: {
  activeStep?: WorkflowStep;
  needsDiagnosisCount: number;
  readyToFixCount: number;
  activeError?: ErrorQueueItem | null;
}) {
  const steps = [
    {
      id: "trigger" as const,
      icon: Zap,
      title: "Trigger an error",
      description: "Generate a controlled Kubernetes failure.",
      cta: { label: "Trigger Error", href: "/scenarios" },
    },
    {
      id: "diagnose" as const,
      icon: Activity,
      title: "Diagnose the error",
      description:
        needsDiagnosisCount === 1
          ? "1 error waiting for diagnosis."
          : `${needsDiagnosisCount} errors waiting for diagnosis.`,
      cta: { label: "View Errors", href: "/errors" },
    },
    {
      id: "fix" as const,
      icon: Wrench,
      title: "Apply a fix",
      description:
        readyToFixCount === 1
          ? "1 diagnosed incident ready for remediation."
          : `${readyToFixCount} diagnosed incidents ready for remediation.`,
      cta: { label: "Review Fixes", href: "/errors?filter=diagnosed" },
    },
  ];

  return (
    <nav aria-label="Incident workflow">
      <ol className="grid gap-4 md:grid-cols-3">
        {steps.map((step, index) => {
          const isActive = activeStep === step.id;
          const isCompleted =
            (step.id === "trigger" && activeStep !== "trigger") ||
            (step.id === "diagnose" && activeStep === "fix");
          const isLast = index === steps.length - 1;

          let ctaHref = step.cta.href;
          let ctaLabel = step.cta.label;

          if (step.id === "diagnose" && activeError?.status === "triggered") {
            ctaHref = `/errors?id=${activeError.id}`;
            ctaLabel = "Diagnose Error";
          }
          if (
            step.id === "fix" &&
            activeError?.status === "diagnosed" &&
            activeError.incidentId
          ) {
            ctaHref = `/errors?id=${activeError.id}`;
            ctaLabel = "Apply Fix";
          }

          return (
            <li
              key={step.id}
              className={cn(
                "relative flex flex-col gap-4 rounded-2xl border border-white/[0.06] bg-gradient-to-b from-white/[0.07] to-white/[0.02] p-5 shadow-card transition-all duration-300",
                isActive && "ring-1 ring-accent-indigo/40 shadow-glow",
                isCompleted && "opacity-80",
              )}
            >
              {!isLast ? (
                <span
                  aria-hidden
                  className="absolute top-1/2 -right-2 hidden h-px w-4 bg-white/10 md:block"
                />
              ) : null}
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "flex size-9 shrink-0 items-center justify-center rounded-full border",
                    isActive
                      ? "border-accent-indigo/40 bg-accent-indigo/10 text-accent-indigo"
                      : isCompleted
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                        : "border-white/10 bg-white/[0.03] text-muted-foreground",
                  )}
                >
                  {isCompleted ? (
                    <Check className="size-4" />
                  ) : (
                    <step.icon className="size-4" />
                  )}
                </span>
                <div className="flex-1">
                  <h3 className="font-semibold">{step.title}</h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </div>
              <Button
                asChild
                className="w-full"
                variant={isActive ? "default" : "secondary"}
              >
                <Link href={ctaHref}>
                  {step.id === "trigger" ? <Zap /> : null}
                  {step.id === "diagnose" && activeError?.status === "diagnosing" ? (
                    <LoaderCircle className="animate-spin" />
                  ) : null}
                  {step.id === "fix" && activeError?.status === "fixing" ? (
                    <LoaderCircle className="animate-spin" />
                  ) : null}
                  {ctaLabel}
                </Link>
              </Button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
