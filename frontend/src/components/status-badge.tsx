import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { FailureCategory, JobStatus, Severity } from "@/types";

// ---------------------------------------------------------------------------
// Job status
// ---------------------------------------------------------------------------

const JOB_STATUS_STYLES: Record<JobStatus, string> = {
  queued: "border-zinc-500/40 bg-zinc-500/10 text-zinc-400",
  collecting: "border-sky-500/40 bg-sky-500/10 text-sky-400",
  processing: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  llm_call: "border-violet-500/40 bg-violet-500/10 text-violet-400",
  persisting: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  done: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  failed: "border-red-500/40 bg-red-500/10 text-red-400",
};

const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  collecting: "Collecting",
  processing: "Processing",
  llm_call: "LLM call",
  persisting: "Persisting",
  done: "Done",
  failed: "Failed",
};

export function JobStatusBadge({
  status,
  className,
}: {
  status: JobStatus;
  className?: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn(JOB_STATUS_STYLES[status], className)}
    >
      {JOB_STATUS_LABELS[status]}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Severity
// ---------------------------------------------------------------------------

const SEVERITY_STYLES: Record<Severity, string> = {
  low: "border-zinc-500/40 bg-zinc-500/10 text-zinc-400",
  medium: "border-sky-500/40 bg-sky-500/10 text-sky-400",
  high: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  critical: "border-red-500/40 bg-red-500/10 text-red-400",
};

export function SeverityBadge({
  severity,
  className,
}: {
  severity: Severity;
  className?: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", SEVERITY_STYLES[severity], className)}
    >
      {severity}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Failure category
// ---------------------------------------------------------------------------

const CATEGORY_STYLES: Record<FailureCategory, string> = {
  crash: "border-red-500/40 bg-red-500/10 text-red-400",
  config: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  dependency: "border-violet-500/40 bg-violet-500/10 text-violet-400",
  network: "border-cyan-500/40 bg-cyan-500/10 text-cyan-400",
  image: "border-orange-500/40 bg-orange-500/10 text-orange-400",
  resource: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  probe: "border-pink-500/40 bg-pink-500/10 text-pink-400",
  unknown: "border-zinc-500/40 bg-zinc-500/10 text-zinc-400",
};

export function CategoryBadge({
  category,
  className,
}: {
  category: FailureCategory;
  className?: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", CATEGORY_STYLES[category], className)}
    >
      {category}
    </Badge>
  );
}
