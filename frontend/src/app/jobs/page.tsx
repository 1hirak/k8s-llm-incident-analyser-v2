"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ListChecks,
  RotateCw,
  Trash2,
  XCircle,
} from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { JobStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ApiError,
  cancelActiveJobs,
  clearJobQueue,
  listJobs,
} from "@/lib/api";
import { formatDateTime, formatLatency, shortId } from "@/lib/utils";
import type { JobListResponse, JobStatus } from "@/types";

const PAGE_SIZE = 15;

const STATUS_OPTIONS: { value: "all" | JobStatus; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "collecting", label: "Collecting" },
  { value: "processing", label: "Processing" },
  { value: "llm_call", label: "LLM call" },
  { value: "persisting", label: "Persisting" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
];

export default function JobsPage() {
  const [data, setData] = useState<JobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | JobStatus>("all");
  const [offset, setOffset] = useState(0);
  const [clearing, setClearing] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(
        await listJobs({
          status: statusFilter === "all" ? undefined : statusFilter,
          limit: PAGE_SIZE,
          offset,
        }),
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load jobs.",
      );
    } finally {
      setLoading(false);
    }
  }, [statusFilter, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const count = data?.count ?? 0;
  const from = count === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, count);

  async function onClearQueue() {
    if (!window.confirm("Delete all pending queue entries? Running analyses will continue.")) {
      return;
    }
    setClearing(true);
    try {
      const result = await clearJobQueue();
      await load();
      window.alert(
        `Cleared ${result.cleared} pending queue entr${result.cleared === 1 ? "y" : "ies"}.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to clear the queue.");
    } finally {
      setClearing(false);
    }
  }

  async function onCancelActive() {
    if (!window.confirm("Cancel all running diagnosis jobs?")) return;
    setCancelling(true);
    try {
      const result = await cancelActiveJobs();
      await load();
      window.alert(
        `Cancelled ${result.cancelled} active diagnosis${result.cancelled === 1 ? "" : "es"}.`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to cancel active diagnoses.",
      );
    } finally {
      setCancelling(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Activity"
        description="Technical analysis job history — backend pipeline runs, newest first"
      >
        <Select
          value={statusFilter}
          onValueChange={(value) => {
            setStatusFilter(value as "all" | JobStatus);
            setOffset(0);
          }}
        >
          <SelectTrigger className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="icon"
          onClick={load}
          disabled={loading}
          aria-label="Refresh"
        >
          <RotateCw className={loading ? "animate-spin" : undefined} />
        </Button>
        <Button
          variant="outline"
          onClick={onClearQueue}
          disabled={clearing}
          title="Delete all pending queue entries"
        >
          <Trash2 />
          {clearing ? "Clearing…" : "Clear queue"}
        </Button>
        <Button
          variant="outline"
          onClick={onCancelActive}
          disabled={cancelling}
          title="Cancel all running diagnosis jobs"
        >
          <XCircle />
          {cancelling ? "Cancelling…" : "Cancel active"}
        </Button>
      </PageHeader>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading && !data ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="No jobs found"
          description={
            statusFilter === "all"
              ? "No analysis jobs have been created yet."
              : "No jobs match this status filter."
          }
        >
          <Button asChild>
            <Link href="/errors">Go to Errors</Link>
          </Button>
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Detail</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Report</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((job) => (
                <TableRow key={job.job_id}>
                  <TableCell className="font-mono text-xs">
                    {shortId(job.job_id)}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {job.namespace}/{job.pod_name}
                  </TableCell>
                  <TableCell>
                    <JobStatusBadge status={job.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-[280px] truncate text-xs">
                    {job.status === "failed"
                      ? (job.error ?? "—")
                      : (job.stage ?? "—")}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatLatency(job.latency_ms)}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {formatDateTime(job.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {job.status === "done" && job.incident_id ? (
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/reports/${job.incident_id}`}>View</Link>
                      </Button>
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="flex items-center justify-between">
            <p className="text-muted-foreground text-sm">
              Showing {from}–{to} of {count}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0 || loading}
              >
                <ChevronLeft />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= count || loading}
              >
                Next
                <ChevronRight />
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
