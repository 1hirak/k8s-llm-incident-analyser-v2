import { Check, Circle, LoaderCircle, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { JobStatus } from "@/types";

const STAGES = [
  {
    status: "queued",
    label: "Queued",
    description: "Job accepted and waiting to run",
  },
  {
    status: "collecting",
    label: "Collecting",
    description: "Gathering logs, events and pod status",
  },
  {
    status: "processing",
    label: "Processing",
    description: "Filtering logs and redacting secrets",
  },
  {
    status: "llm_call",
    label: "LLM call",
    description: "Analysing the evidence with the LLM",
  },
  {
    status: "persisting",
    label: "Persisting",
    description: "Saving the incident report",
  },
  {
    status: "done",
    label: "Done",
    description: "Report ready",
  },
] as const;

type StageStatus = (typeof STAGES)[number]["status"];

/**
 * Vertical stepper for the analysis pipeline.
 *
 * `status` is the last known pipeline stage. When `failed` is true the
 * current stage is rendered as the failing one.
 */
export function PipelineTimeline({
  status,
  failed = false,
  stage,
  className,
}: {
  status: JobStatus;
  failed?: boolean;
  stage?: string | null;
  className?: string;
}) {
  const currentStatus: StageStatus =
    status === "failed" ? "persisting" : status;
  const currentIndex = STAGES.findIndex((s) => s.status === currentStatus);

  return (
    <ol className={cn("space-y-0", className)}>
      {STAGES.map((s, index) => {
        const isCompleted = !failed && index < currentIndex;
        const isCurrent = failed
          ? index === currentIndex
          : index === currentIndex && s.status !== "done";
        const isDone = !failed && s.status === "done" && index <= currentIndex;
        const isLast = index === STAGES.length - 1;

        return (
          <li key={s.status} className="relative flex gap-3 pb-6 last:pb-0">
            {!isLast ? (
              <span
                aria-hidden
                className={cn(
                  "bg-border absolute top-8 left-[15px] h-[calc(100%-2rem)] w-px",
                  (isCompleted || isDone) && "bg-emerald-500/40",
                )}
              />
            ) : null}
            <span
              className={cn(
                "border-border bg-background relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border",
                (isCompleted || isDone) &&
                  "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
                isCurrent &&
                  !failed &&
                  "border-blue-500/40 bg-blue-500/10 text-blue-400",
                isCurrent && failed && "border-red-500/40 bg-red-500/10 text-red-400",
              )}
            >
              {isCompleted || isDone ? (
                <Check className="size-4" />
              ) : isCurrent && failed ? (
                <X className="size-4" />
              ) : isCurrent ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Circle className="text-muted-foreground/40 size-4" />
              )}
            </span>
            <div className="flex min-w-0 flex-col gap-0.5 pt-1.5">
              <span
                className={cn(
                  "text-sm font-medium",
                  !isCompleted && !isCurrent && !isDone && "text-muted-foreground",
                )}
              >
                {s.label}
              </span>
              <span className="text-muted-foreground text-xs">
                {isCurrent && stage ? stage : s.description}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
