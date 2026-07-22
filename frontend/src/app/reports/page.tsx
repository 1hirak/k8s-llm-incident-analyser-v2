"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  RotateCw,
  X,
} from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ReportsTable } from "@/components/reports-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, listReports } from "@/lib/api";
import type {
  FailureCategory,
  ReportListResponse,
  Severity,
} from "@/types";

const PAGE_SIZE = 15;

const CATEGORY_OPTIONS: { value: "all" | FailureCategory; label: string }[] = [
  { value: "all", label: "All categories" },
  { value: "crash", label: "Crash" },
  { value: "config", label: "Config" },
  { value: "dependency", label: "Dependency" },
  { value: "network", label: "Network" },
  { value: "image", label: "Image" },
  { value: "resource", label: "Resource" },
  { value: "probe", label: "Probe" },
  { value: "unknown", label: "Unknown" },
];

const SEVERITY_OPTIONS: { value: "all" | Severity; label: string }[] = [
  { value: "all", label: "All severities" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" },
];

interface Filters {
  namespace: string;
  pod_name: string;
  category: "all" | FailureCategory;
  severity: "all" | Severity;
}

const EMPTY_FILTERS: Filters = {
  namespace: "",
  pod_name: "",
  category: "all",
  severity: "all",
};

export default function ReportsPage() {
  const [data, setData] = useState<ReportListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(
        await listReports({
          namespace: applied.namespace || undefined,
          pod_name: applied.pod_name || undefined,
          category: applied.category === "all" ? undefined : applied.category,
          severity: applied.severity === "all" ? undefined : applied.severity,
          limit: PAGE_SIZE,
          offset,
        }),
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load reports.",
      );
    } finally {
      setLoading(false);
    }
  }, [applied, offset]);

  useEffect(() => {
    load();
  }, [load]);

  function applyFilters(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setApplied(draft);
  }

  function clearFilters() {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setOffset(0);
  }

  const count = data?.count ?? 0;
  const from = count === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, count);
  const hasFilters =
    applied.namespace !== "" ||
    applied.pod_name !== "" ||
    applied.category !== "all" ||
    applied.severity !== "all";

  return (
    <>
      <PageHeader
        title="Reports"
        description="Persisted incident reports from the analysis pipeline"
      >
        <Button
          variant="outline"
          size="icon"
          onClick={load}
          disabled={loading}
          aria-label="Refresh"
        >
          <RotateCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </PageHeader>

      <form
        onSubmit={applyFilters}
        className="mb-4 flex flex-wrap items-center gap-2"
      >
        <Input
          value={draft.namespace}
          onChange={(e) => setDraft({ ...draft, namespace: e.target.value })}
          placeholder="Namespace"
          className="w-40"
        />
        <Input
          value={draft.pod_name}
          onChange={(e) => setDraft({ ...draft, pod_name: e.target.value })}
          placeholder="Pod name"
          className="w-40"
        />
        <Select
          value={draft.category}
          onValueChange={(value) =>
            setDraft({ ...draft, category: value as Filters["category"] })
          }
        >
          <SelectTrigger className="w-[150px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CATEGORY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={draft.severity}
          onValueChange={(value) =>
            setDraft({ ...draft, severity: value as Filters["severity"] })
          }
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEVERITY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button type="submit" variant="secondary">
          Apply filters
        </Button>
        {hasFilters ? (
          <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>
            <X />
            Clear
          </Button>
        ) : null}
      </form>

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
          icon={FileText}
          title="No reports found"
          description={
            hasFilters
              ? "No reports match the current filters."
              : "No incident reports have been persisted yet."
          }
        >
          {hasFilters ? (
            <Button variant="outline" onClick={clearFilters}>
              Clear filters
            </Button>
          ) : (
            <Button asChild>
              <Link href="/analyse">Run an analysis</Link>
            </Button>
          )}
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <ReportsTable reports={data.items} />

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
