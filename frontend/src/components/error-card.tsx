"use client";

import Link from "next/link";
import { CheckCircle2, Play, RotateCcw, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { ErrorQueueItem } from "@/types";

export const ERROR_STATUS_LABELS: Record<ErrorQueueItem["status"], string> = {
  triggered: "Needs diagnosis",
  diagnosing: "Diagnosing",
  diagnosed: "Diagnosis complete",
  diagnosis_failed: "Diagnosis failed",
  fixing: "Applying fix",
  fixed: "Fixed",
};

const ERROR_STATUS_STYLES: Record<ErrorQueueItem["status"], string> = {
  triggered: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  diagnosing: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  diagnosed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  diagnosis_failed: "border-red-500/40 bg-red-500/10 text-red-400",
  fixing: "border-violet-500/40 bg-violet-500/10 text-violet-400",
  fixed: "border-zinc-500/40 bg-zinc-500/10 text-zinc-400",
};

export function ErrorStatusBadge({
  status,
  className,
}: {
  status: ErrorQueueItem["status"];
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        ERROR_STATUS_STYLES[status],
        className,
      )}
    >
      {ERROR_STATUS_LABELS[status]}
    </span>
  );
}

export function ErrorCard({
  item,
  highlighted,
  onSelect,
  onStartDiagnosis,
  onApplyFix,
  onMarkCompleted,
}: {
  item: ErrorQueueItem;
  highlighted?: boolean;
  onSelect?: (item: ErrorQueueItem) => void;
  onStartDiagnosis?: (item: ErrorQueueItem) => void;
  onApplyFix?: (item: ErrorQueueItem) => void;
  onMarkCompleted?: (item: ErrorQueueItem) => void;
}) {
  const detailHref = `/errors?id=${item.id}`;
  const canDiagnose =
    item.status === "triggered" || item.status === "diagnosis_failed";
  const isDiagnosing = item.status === "diagnosing";
  const isDiagnosed = item.status === "diagnosed" && item.incidentId;
  const isFixed = item.status === "fixed";

  function handleDiagnoseClick(event: React.MouseEvent) {
    event.preventDefault();
    onStartDiagnosis?.(item);
  }

  function handleApplyFixClick(event: React.MouseEvent) {
    event.preventDefault();
    onApplyFix?.(item);
  }

  function handleMarkCompletedClick(event: React.MouseEvent) {
    event.preventDefault();
    onMarkCompleted?.(item);
  }

  function handleViewClick(event: React.MouseEvent) {
    event.preventDefault();
    onSelect?.(item);
  }

  return (
    <Card
      onClick={onSelect ? () => onSelect(item) : undefined}
      className={cn(
        "cursor-pointer transition-all duration-200 hover:border-white/15 hover:bg-white/[0.045]",
        highlighted && "ring-1 ring-accent-indigo/40 shadow-glow",
      )}
    >
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <ErrorStatusBadge status={item.status} />
          {item.category ? <CategoryBadge category={item.category} /> : null}
          {item.severity ? <SeverityBadge severity={item.severity} /> : null}
        </div>
        <CardTitle className="text-base">
          {item.scenarioName ?? `Error in ${item.namespace}/${item.podName}`}
        </CardTitle>
        <CardDescription className="font-mono text-xs">
          {item.namespace}/{item.podName}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex-1">
        <p className="text-muted-foreground text-sm">
          Triggered {formatRelativeTime(item.triggeredAt)}
        </p>
      </CardContent>
      <CardFooter className="flex-col gap-2 sm:flex-row">
        {isFixed ? (
          <Button
            asChild
            variant="outline"
            className="w-full sm:w-auto"
            onClick={handleViewClick}
          >
            <Link href={detailHref}>View Diagnosis</Link>
          </Button>
        ) : canDiagnose ? (
          <Button
            onClick={handleDiagnoseClick}
            disabled={isDiagnosing}
            className="w-full sm:w-auto"
          >
            {item.status === "diagnosis_failed" ? (
              <>
                <RotateCcw />
                Retry Diagnosis
              </>
            ) : (
              <>
                <Play />
                Diagnose
              </>
            )}
          </Button>
        ) : isDiagnosing ? (
          <Button
            onClick={handleDiagnoseClick}
            variant="outline"
            className="w-full sm:w-auto"
          >
            <RotateCcw />
            Re-diagnose
          </Button>
        ) : null}

        {isDiagnosed ? (
          <>
            <Button
              asChild
              variant="outline"
              className="w-full sm:w-auto"
              onClick={handleViewClick}
            >
              <Link href={detailHref}>View Diagnosis</Link>
            </Button>
            <Button
              onClick={handleApplyFixClick}
              className="w-full sm:w-auto"
            >
              <Wrench />
              Apply Fix
            </Button>
            <Button
              onClick={handleMarkCompletedClick}
              variant="outline"
              className="w-full sm:w-auto"
            >
              <CheckCircle2 />
              Mark as Completed
            </Button>
          </>
        ) : null}
      </CardFooter>
    </Card>
  );
}
