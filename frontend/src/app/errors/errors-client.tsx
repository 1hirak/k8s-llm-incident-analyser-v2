"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  Check,
  Inbox,
  Plus,
  RotateCcw,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { ApplyFixDialog } from "@/components/apply-fix-dialog";
import { ErrorCard } from "@/components/error-card";
import { ErrorDetail } from "@/components/error-detail";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDiagnosisJob } from "@/hooks/use-diagnosis-job";
import {
  ApiError,
  cancelActiveJobs,
  cancelJob,
  getJob,
  getReport,
  resetScenarios,
} from "@/lib/api";
import {
  clearErrorQueue,
  loadErrorQueue,
  markAllActiveScenarioErrorsFixed,
  updateErrorQueueItem,
  type ErrorQueueItem,
} from "@/lib/error-queue";
import type { SseDoneEvent, SseFailedEvent } from "@/types";

type Filter = "active" | "needs_diagnosis" | "diagnosed" | "fixed" | "all";

const FILTER_LABELS: Record<Filter, string> = {
  active: "Active",
  needs_diagnosis: "Needs Diagnosis",
  diagnosed: "Diagnosed",
  fixed: "Fixed",
  all: "All",
};

function matchesFilter(item: ErrorQueueItem, filter: Filter): boolean {
  switch (filter) {
    case "active":
      return item.status !== "fixed";
    case "needs_diagnosis":
      return item.status === "triggered" || item.status === "diagnosis_failed";
    case "diagnosed":
      return item.status === "diagnosed";
    case "fixed":
      return item.status === "fixed";
    case "all":
    default:
      return true;
  }
}

export function ErrorsClient() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [queue, setQueue] = useState<ErrorQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fixItem, setFixItem] = useState<ErrorQueueItem | null>(null);
  const [fixReport, setFixReport] = useState<Awaited<
    ReturnType<typeof getReport>
  > | null>(null);
  const [fixReportError, setFixReportError] = useState<string | null>(null);
  const [resettingWorkload, setResettingWorkload] = useState(false);
  const diagnosisItemRef = useRef<string | null>(null);
  const pendingDiagnosisItemsRef = useRef(new Set<string>());

  const filterParam = searchParams.get("filter") as Filter | null;
  const filter: Filter =
    filterParam && FILTER_LABELS[filterParam] ? filterParam : "active";

  const refreshQueue = useCallback(() => {
    setQueue(loadErrorQueue());
  }, []);

  useEffect(() => {
    refreshQueue();
    setLoading(false);

    function onStorage(event: StorageEvent) {
      if (event.key === "k8s-incident-analyser.error-queue.v1") {
        refreshQueue();
      }
    }

    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [refreshQueue]);

  useEffect(() => {
    const id = searchParams.get("id");
    setSelectedId(id);
  }, [searchParams]);

  const handleDiagnosisDone = useCallback(
    (event: SseDoneEvent) => {
      const item = loadErrorQueue().find((i) => i.jobId === event.job_id);
      if (!item) return;
      const updated = updateErrorQueueItem(item.id, {
        status: "diagnosed",
        incidentId: event.incident_id,
        diagnosisError: undefined,
      });
      if (updated) {
        if (diagnosisItemRef.current === item.id) {
          diagnosisItemRef.current = null;
        }
        refreshQueue();
      }
    },
    [refreshQueue],
  );

  const handleDiagnosisFailed = useCallback(
    (event: SseFailedEvent) => {
      const queue = loadErrorQueue();
      const item = event.job_id
        ? queue.find((candidate) => candidate.jobId === event.job_id)
        : diagnosisItemRef.current
          ? queue.find((candidate) => candidate.id === diagnosisItemRef.current)
          : undefined;
      if (!item || item.status !== "diagnosing") return;

      const updated = updateErrorQueueItem(item.id, {
        status: "diagnosis_failed",
        diagnosisError: event.error,
      });
      if (updated) {
        if (diagnosisItemRef.current === item.id) {
          diagnosisItemRef.current = null;
        }
        refreshQueue();
      }
    },
    [refreshQueue],
  );

  const {
    phase,
    status,
    stage,
    failedEvent,
    activity,
    startDiagnosis,
    reset: resetDiagnosis,
  } = useDiagnosisJob({
    onDone: handleDiagnosisDone,
    onFailed: handleDiagnosisFailed,
  });

  const reconcileDiagnoses = useCallback(async () => {
    const diagnosing = loadErrorQueue().filter(
      (item) => item.status === "diagnosing",
    );
    if (diagnosing.length === 0) return;

    await Promise.all(
      diagnosing.map(async (item) => {
        if (!item.jobId) {
          if (pendingDiagnosisItemsRef.current.has(item.id)) return;
          updateErrorQueueItem(item.id, {
            status: "diagnosis_failed",
            diagnosisError: "Diagnosis was interrupted before a job was created.",
          });
          return;
        }

        try {
          const job = await getJob(item.jobId);
          if (job.status === "done" && job.incident_id) {
            updateErrorQueueItem(item.id, {
              status: "diagnosed",
              incidentId: job.incident_id,
              diagnosisError: undefined,
            });
          } else if (job.status === "failed") {
            updateErrorQueueItem(item.id, {
              status: "diagnosis_failed",
              diagnosisError: job.error ?? "Diagnosis failed.",
            });
          }
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            updateErrorQueueItem(item.id, {
              status: "diagnosis_failed",
              diagnosisError: "The diagnosis job is no longer available.",
            });
          }
        }
      }),
    );
    refreshQueue();
  }, [refreshQueue]);

  useEffect(() => {
    void reconcileDiagnoses();
    const intervalId = window.setInterval(() => {
      void reconcileDiagnoses();
    }, 2000);
    return () => window.clearInterval(intervalId);
  }, [reconcileDiagnoses]);

  const filteredItems = useMemo(
    () => queue.filter((item) => matchesFilter(item, filter)),
    [queue, filter],
  );

  const selectedItem = useMemo(
    () =>
      selectedId ? (queue.find((item) => item.id === selectedId) ?? null) : null,
    [selectedId, queue],
  );

  function setFilter(next: Filter) {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "active") {
      params.delete("filter");
    } else {
      params.set("filter", next);
    }
    router.replace(`/errors?${params.toString()}`);
  }

  function selectItem(item: ErrorQueueItem) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("id", item.id);
    router.replace(`/errors?${params.toString()}`, { scroll: false });
  }

  async function startDiagnosisForItem(item: ErrorQueueItem) {
    const currentItem =
      loadErrorQueue().find((candidate) => candidate.id === item.id) ?? item;
    resetDiagnosis();

    if (currentItem.status === "diagnosing" && currentItem.jobId) {
      try {
        await cancelJob(currentItem.jobId);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) {
          updateErrorQueueItem(currentItem.id, {
            status: "diagnosis_failed",
            diagnosisError:
              error instanceof ApiError
                ? error.message
                : "Could not stop the previous diagnosis.",
          });
          refreshQueue();
          toast.error("Could not restart diagnosis", {
            description: "The previous diagnosis is still running.",
          });
          return;
        }
      }
    }

    diagnosisItemRef.current = item.id;
    pendingDiagnosisItemsRef.current.add(item.id);
    updateErrorQueueItem(item.id, {
      status: "diagnosing",
      jobId: undefined,
      incidentId: undefined,
      diagnosisError: undefined,
    });
    refreshQueue();
    selectItem(item);
    try {
      const jobId = await startDiagnosis(item.namespace, item.podName);
      if (jobId) {
        updateErrorQueueItem(item.id, { jobId, diagnosisError: undefined });
        refreshQueue();
      } else if (
        loadErrorQueue().some(
          (candidate) =>
            candidate.id === item.id && candidate.status === "diagnosing",
        )
      ) {
        updateErrorQueueItem(item.id, {
          status: "diagnosis_failed",
          diagnosisError: "Failed to create the diagnosis job.",
        });
        refreshQueue();
      }
    } finally {
      pendingDiagnosisItemsRef.current.delete(item.id);
      diagnosisItemRef.current = null;
    }
  }

  async function handleApplyFix(item: ErrorQueueItem) {
    setFixItem(item);
    setFixReport(null);
    setFixReportError(null);
    if (item.incidentId) {
      try {
        const report = await getReport(item.incidentId);
        setFixReport(report);
      } catch (err) {
        setFixReportError(
          err instanceof ApiError ? err.message : "Failed to load report.",
        );
      }
    }
  }

  function handleFixed() {
    resetDiagnosis();
    refreshQueue();
    setFixItem(null);
  }

  async function handleMarkCompleted(item: ErrorQueueItem) {
    if (item.source === "scenario") {
      if (
        !window.confirm(
          "Restore the demo workload and mark all active demo incidents as completed?",
        )
      ) {
        return;
      }

      try {
        await cancelActiveJobs();
        await resetScenarios();
        markAllActiveScenarioErrorsFixed();
        resetDiagnosis();
        refreshQueue();
        toast.success("Incident marked as completed", {
          description: "The demo workload has been restored.",
        });
      } catch (error) {
        toast.error("Could not complete the incident", {
          description:
            error instanceof ApiError ? error.message : "Unexpected error.",
        });
      }
      return;
    }

    const updated = updateErrorQueueItem(item.id, {
      status: "fixed",
      fixedAt: new Date().toISOString(),
    });
    if (!updated) return;
    resetDiagnosis();
    refreshQueue();
    toast.success("Incident marked as completed", {
      description: "The incident was closed without changing the cluster.",
    });
  }

  function clearLocalQueue() {
    clearErrorQueue();
    resetDiagnosis();
    diagnosisItemRef.current = null;
    setQueue([]);
    setSelectedId(null);
    setFixItem(null);
    setFixReport(null);
    setFixReportError(null);

    const params = new URLSearchParams(searchParams.toString());
    params.delete("id");
    const query = params.toString();
    router.replace(query ? `/errors?${query}` : "/errors", { scroll: false });
  }

  function handleClearQueue() {
    if (
      !window.confirm(
        "Clear local queue history? Running diagnoses and demo faults will continue.",
      )
    ) {
      return;
    }
    clearLocalQueue();
    toast.success("Local queue history cleared");
  }

  async function handleResetWorkload() {
    if (
      !window.confirm(
        "Cancel active diagnoses, restore the demo workload, and clear the local queue?",
      )
    ) {
      return;
    }

    setResettingWorkload(true);
    try {
      await cancelActiveJobs();
      await resetScenarios();
      clearLocalQueue();
      toast.success("Demo workload reset", {
        description: "You can trigger the same scenario again.",
      });
    } catch (error) {
      toast.error("Could not reset the demo workload", {
        description:
          error instanceof ApiError ? error.message : "Unexpected error.",
      });
    } finally {
      setResettingWorkload(false);
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader
          title="Error Queue"
          description="One focused workspace for every triggered incident. Select an error to open its diagnosis beside the queue."
        />
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-32 animate-pulse rounded-2xl bg-white/[0.03]"
            />
          ))}
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        kicker="Incident workflow · live queue"
        title="Error Queue"
        description="One focused workspace for every triggered incident. Select an error to open its diagnosis beside the queue."
      >
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="destructive"
            onClick={handleClearQueue}
            disabled={queue.length === 0}
          >
            <Trash2 />
            Clear Local History
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handleResetWorkload}
            disabled={resettingWorkload}
          >
            <RotateCcw className={resettingWorkload ? "animate-spin" : undefined} />
            {resettingWorkload ? "Resetting…" : "Reset Demo & Clear"}
          </Button>
          <Button asChild variant="outline">
            <Link href="/scenarios">
              <Plus />
              Trigger Error
            </Link>
          </Button>
        </div>
      </PageHeader>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="metric-tile"><span className="metric-icon text-amber-300"><ShieldAlert className="size-4" /></span><span><strong>{queue.filter((item) => item.status !== "fixed").length}</strong><small>needs attention</small></span></div>
        <div className="metric-tile"><span className="metric-icon text-cyan-300"><Inbox className="size-4" /></span><span><strong>{queue.length}</strong><small>total queue items</small></span></div>
        <div className="metric-tile"><span className="metric-icon text-emerald-300"><Check className="size-4" /></span><span><strong>{queue.filter((item) => item.status === "fixed").length}</strong><small>resolved</small></span></div>
      </div>

      <Tabs
        value={filter}
        onValueChange={(v) => setFilter(v as Filter)}
        className="mb-6"
      >
        <TabsList className="flex h-auto w-full flex-wrap gap-1 p-1 sm:w-fit sm:flex-nowrap">
          {(Object.keys(FILTER_LABELS) as Filter[]).map((key) => (
            <TabsTrigger key={key} value={key} className="flex-1 sm:flex-none">
              {FILTER_LABELS[key]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {queue.length === 0 ? (
        <EmptyState
          icon={Activity}
          title="No errors yet"
          description="Generate a controlled Kubernetes failure to try the incident-response workflow."
        >
          <Button asChild>
            <Link href="/scenarios">Trigger an Error</Link>
          </Button>
        </EmptyState>
      ) : filteredItems.length === 0 ? (
        <EmptyState
          icon={Activity}
          title={`No ${FILTER_LABELS[filter].toLowerCase()} errors`}
          description="Try a different filter or trigger a new error."
        >
          <Button asChild variant="outline">
            <Link href="/scenarios">Trigger an Error</Link>
          </Button>
        </EmptyState>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
          <div className="space-y-3">
            <div className="mb-1 flex items-center justify-between px-1">
              <p className="eyebrow">{filteredItems.length} {FILTER_LABELS[filter].toLowerCase()} incidents</p>
              <span className="text-xs text-muted-foreground">Click a row to inspect</span>
            </div>
            {filteredItems.map((item) => (
              <ErrorCard
                key={item.id}
                item={item}
                highlighted={selectedId === item.id}
                onSelect={selectItem}
                onStartDiagnosis={startDiagnosisForItem}
                onApplyFix={handleApplyFix}
                onMarkCompleted={handleMarkCompleted}
              />
            ))}
          </div>
          {selectedItem ? (
            <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
              <ErrorDetail
                item={selectedItem}
                onApplyFix={handleApplyFix}
                onStartDiagnosis={startDiagnosisForItem}
                onMarkCompleted={handleMarkCompleted}
                diagnosisPhase={phase}
                jobStatus={status}
                stage={stage}
                failedEvent={failedEvent}
                activity={activity}
              />
            </div>
          ) : (
            <div className="hidden rounded-2xl border border-dashed border-white/10 bg-white/[0.018] p-8 lg:flex lg:min-h-[360px] lg:flex-col lg:items-center lg:justify-center lg:text-center">
              <span className="rounded-xl bg-white/[0.06] p-3 text-muted-foreground"><ArrowRight className="size-5" /></span>
              <p className="mt-4 font-medium">Select an incident</p>
              <p className="mt-2 max-w-xs text-sm leading-6 text-muted-foreground">The diagnosis workspace opens here, keeping the queue and your next action in view.</p>
            </div>
          )}
        </div>
      )}

      <ApplyFixDialog
        item={fixItem}
        report={fixReportError ? null : fixReport}
        open={fixItem !== null}
        onOpenChange={(open) => {
          if (!open) {
            setFixItem(null);
            setFixReport(null);
            setFixReportError(null);
          }
        }}
        onFixed={handleFixed}
      />
    </>
  );
}
