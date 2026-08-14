import { useEffect, useState } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  ChevronRight,
  Circle,
  LoaderCircle,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react";

import { cn, formatLatency } from "@/lib/utils";
import type { JobStatus } from "@/types";
import type { ActivityEntry } from "@/hooks/use-diagnosis-job";
import type { LLMConfig } from "@/hooks/use-llm-config";

const PIPELINE_STAGES: {
  status: JobStatus;
  label: string;
  description: string;
}[] = [
  {
    status: "collecting",
    label: "Collecting evidence",
    description: "Gathering logs, events and pod status",
  },
  {
    status: "processing",
    label: "Processing evidence",
    description: "Filtering logs and redacting secrets",
  },
  {
    status: "llm_call",
    label: "Analysing with AI",
    description: "Analysing filtered and redacted evidence",
  },
  {
    status: "persisting",
    label: "Creating diagnosis",
    description: "Saving the incident report",
  },
];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** "14:03:25" (UTC, deterministic) timestamp for activity log lines. */
function formatLogTime(at: number): string {
  const d = new Date(at);
  return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())}`;
}

type ActivityLine = {
  icon: "sent" | "waiting" | "received" | "error";
  text: string;
  at: number;
};

/**
 * ChatGPT-"Thinking"-style collapsible trace of what happens behind the
 * scenes while the redacted evidence package is analysed by the LLM.
 * Every line is derived from a real SSE event received for the job.
 */
function LlmActivityLog({
  entries,
  live,
}: {
  entries: ActivityEntry[];
  /** True while the llm_call stage is the current, non-failed stage. */
  live: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [live]);

  const startIndex = entries.findIndex((e) => e.status === "llm_call");
  if (startIndex === -1) return null;

  const start = entries[startIndex];
  const end = entries
    .slice(startIndex + 1)
    .find((e) => e.status !== "llm_call");

  const lines: ActivityLine[] = [
    {
      icon: "sent",
      text: "Redacted evidence package sent to llm-svc · POST /analyse",
      at: start.at,
    },
  ];

  if (!end && live) {
    lines.push({
      icon: "waiting",
      text: `${start.detail || "Waiting for the model"} — ${Math.max(0, Math.round((now - start.at) / 1000))}s elapsed`,
      at: now,
    });
  } else if (end && end.kind === "failed") {
    lines.push({
      icon: "error",
      text: `llm-svc returned an error after ${formatLatency(end.at - start.at)} — ${end.detail}`,
      at: end.at,
    });
  } else if (end) {
    lines.push({
      icon: "received",
      text: `Response received after ${formatLatency(end.at - start.at)} — incident report validated`,
      at: end.at,
    });
  }

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-xs transition-colors"
      >
        <ChevronRight
          className={cn(
            "size-3.5 transition-transform",
            open && "rotate-90",
          )}
        />
        <span>Behind the scenes</span>
        {live ? (
          <span className="text-accent-indigo flex items-center gap-1 text-[10px]">
            <span className="bg-accent-indigo size-1.5 animate-pulse rounded-full" />
            {Math.max(0, Math.round((now - start.at) / 1000))}s
          </span>
        ) : null}
      </button>
      {open ? (
        <ol className="border-border/60 mt-2 space-y-1.5 rounded-lg border bg-white/[0.02] px-3 py-2.5 font-mono text-[11px] leading-relaxed">
          {lines.map((line, i) => (
            <li key={i} className="flex items-start gap-2">
              {line.icon === "sent" ? (
                <ArrowUpRight className="text-accent-indigo mt-0.5 size-3 shrink-0" />
              ) : line.icon === "waiting" ? (
                <LoaderCircle className="text-accent-indigo mt-0.5 size-3 shrink-0 animate-spin" />
              ) : line.icon === "received" ? (
                <ArrowDownLeft className="mt-0.5 size-3 shrink-0 text-emerald-400" />
              ) : (
                <X className="mt-0.5 size-3 shrink-0 text-red-400" />
              )}
              <span className="text-muted-foreground shrink-0">
                {formatLogTime(line.at)}
              </span>
              <span
                className={cn(
                  "text-foreground/80 min-w-0 break-words",
                  line.icon === "error" && "text-red-400",
                  line.icon === "received" && "text-emerald-400/90",
                )}
              >
                {line.text}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export function DiagnosisProgress({
  status,
  stage,
  reconnecting,
  failed,
  className,
  llmConfig,
  activity,
}: {
  status: JobStatus;
  stage?: string | null;
  reconnecting?: boolean;
  failed?: boolean;
  className?: string;
  llmConfig?: LLMConfig;
  activity?: ActivityEntry[];
}) {
  const isComplete = status === "done";
  const currentIndex = isComplete
    ? PIPELINE_STAGES.length
    : PIPELINE_STAGES.findIndex((s) => s.status === status);

  return (
    <div
      className={cn("space-y-4", className)}
      role="region"
      aria-live="polite"
      aria-atomic="false"
      aria-label="Diagnosis progress"
    >
      {reconnecting ? (
        <div
          role="status"
          className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-400"
        >
          <WifiOff className="size-4" />
          <span className="text-sm">Connection interrupted. Reconnecting…</span>
        </div>
      ) : null}

      <ol className="space-y-0">
        {PIPELINE_STAGES.map((s, index) => {
          const isCompleted = !failed && (isComplete || index < currentIndex);
          const isCurrent = !failed && !isComplete && index === currentIndex;
          const isDone = !failed && isComplete;
          const isLast = index === PIPELINE_STAGES.length - 1;

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
                    "border-accent-indigo/40 bg-accent-indigo/10 text-accent-indigo",
                  failed &&
                    isCurrent &&
                    "border-red-500/40 bg-red-500/10 text-red-400",
                )}
              >
                {s.status === "llm_call" && (isCompleted || isDone) ? (
                  <Sparkles className="size-4" />
                ) : s.status === "llm_call" && isCurrent && !failed ? (
                  <Sparkles className="size-4 animate-pulse" />
                ) : isCompleted || isDone ? (
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
                    !isCompleted && !isCurrent && !isDone &&
                      "text-muted-foreground",
                  )}
                >
                  {s.label}
                </span>
                <span className="text-muted-foreground text-xs">
                  {isCurrent && stage ? stage : s.description}
                </span>
                {s.status === "llm_call" && (isCurrent || isCompleted || isDone) && llmConfig ? (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                        llmConfig.isMock
                          ? "border-sky-500/40 bg-sky-500/10 text-sky-400"
                          : "border-accent-indigo/40 bg-accent-indigo/10 text-accent-indigo",
                      )}
                    >
                      <Sparkles className="size-3" />
                      {llmConfig.isMock ? "Heuristic" : "AI"} · {llmConfig.providerName}
                      {llmConfig.model && llmConfig.model !== "Free mock classifier" ? (
                        <span className="text-white/50">· {llmConfig.model}</span>
                      ) : null}
                    </span>
                    {isCurrent ? (
                      <span className="text-muted-foreground text-[10px]">
                        Evidence is being analysed by the configured model.
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {s.status === "llm_call" && activity ? (
                  <LlmActivityLog
                    entries={activity}
                    live={isCurrent && !failed}
                  />
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
