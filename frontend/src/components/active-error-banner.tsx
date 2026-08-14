import Link from "next/link";
import { AlertTriangle, LoaderCircle, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import type { ErrorQueueItem } from "@/types";

function statusLabel(status: ErrorQueueItem["status"]): string {
  switch (status) {
    case "triggered":
      return "Needs diagnosis";
    case "diagnosing":
      return "Diagnosing";
    case "diagnosed":
      return "Diagnosis complete";
    case "diagnosis_failed":
      return "Diagnosis failed";
    case "fixing":
      return "Applying fix";
    case "fixed":
      return "Fixed";
    default:
      return "Unknown";
  }
}

export function ActiveErrorBanner({
  errors,
  className,
  onReset,
  resetting = false,
}: {
  errors: ErrorQueueItem[];
  className?: string;
  onReset?: () => void;
  resetting?: boolean;
}) {
  if (errors.length === 0) return null;

  const visibleErrors = errors.slice(0, 3);
  const isSingle = errors.length === 1;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col gap-4 rounded-2xl border border-amber-500/30 bg-gradient-to-r from-amber-500/10 to-transparent p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-400">
          <AlertTriangle className="size-4" />
        </span>
        <div className="space-y-1">
          <p className="text-sm font-medium">
            {isSingle ? "Active simulated error" : `${errors.length} active simulated errors`}
          </p>
          <div className="space-y-1.5">
            {visibleErrors.map((error) => (
              <div key={error.id} className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{error.scenarioName ?? "Unknown error"}</span>
                <span className="text-muted-foreground text-sm">
                  {error.namespace}/{error.podName}
                </span>
                {error.category ? <CategoryBadge category={error.category as never} /> : null}
                {error.severity ? <SeverityBadge severity={error.severity as never} /> : null}
              </div>
            ))}
          </div>
          {errors.length > visibleErrors.length ? (
            <p className="text-muted-foreground text-sm">+{errors.length - visibleErrors.length} more in the Error Queue</p>
          ) : isSingle ? (
            <p className="text-muted-foreground text-sm">{statusLabel(errors[0].status)}</p>
          ) : (
            <p className="text-muted-foreground text-sm">Review the active incidents in the Error Queue</p>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        {onReset ? (
          <Button
            variant="outline"
            onClick={onReset}
            disabled={resetting}
            className="w-full sm:w-auto"
          >
            {resetting ? (
              <LoaderCircle className="animate-spin" />
            ) : (
              <RotateCcw />
            )}
            {resetting ? "Resetting…" : "Reset Demo"}
          </Button>
        ) : null}
        <Button asChild className="w-full sm:w-auto">
          <Link href="/errors">Open Error Queue</Link>
        </Button>
      </div>
    </div>
  );
}
