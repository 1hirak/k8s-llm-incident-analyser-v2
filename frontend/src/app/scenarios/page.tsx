"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, LoaderCircle, Zap } from "lucide-react";
import { toast } from "sonner";

import { ActiveErrorBanner } from "@/components/active-error-banner";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  applyScenario,
  cancelActiveJobs,
  listScenarios,
  resetScenarios,
} from "@/lib/api";
import {
  addErrorQueueItem,
  getActiveScenarioErrors,
  markAllActiveScenarioErrorsFixed,
  type ErrorQueueItem,
} from "@/lib/error-queue";
import type { ScenarioSummary } from "@/types";

export default function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmScenario, setConfirmScenario] =
    useState<ScenarioSummary | null>(null);
  const [applying, setApplying] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [activeErrors, setActiveErrors] = useState<ErrorQueueItem[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listScenarios();
      setScenarios(res.items);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load scenarios.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    setActiveErrors(getActiveScenarioErrors());

    function onStorage(event: StorageEvent) {
      if (event.key === "k8s-incident-analyser.error-queue.v1") {
        setActiveErrors(getActiveScenarioErrors());
      }
    }

    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [load]);

  async function onApplyConfirm() {
    if (!confirmScenario) return;

    setApplying(true);
    try {
      const res = await applyScenario(confirmScenario.scenario_id);

      addErrorQueueItem({
        source: "scenario",
        scenarioId: confirmScenario.scenario_id,
        scenarioName: confirmScenario.name,
        namespace: "demo",
        podName: "demo-app",
        category: confirmScenario.category,
        severity: confirmScenario.severity,
        status: "triggered",
      });

      setActiveErrors(getActiveScenarioErrors());
      toast.success("Error triggered successfully", {
        description: res.fault_description ?? "The fault is now live in the cluster.",
      });
      setConfirmScenario(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.warning("This scenario is already active", {
          description: "Choose a different scenario or reset the demo workload.",
          action: {
            label: "Reset demo",
            onClick: () => void resetDemo(),
          },
        });
      } else {
        toast.error("Failed to trigger error", {
          description:
            err instanceof ApiError ? err.message : "Unexpected error.",
        });
      }
    } finally {
      setApplying(false);
    }
  }

  async function resetDemo() {
    if (resetting) return;
    setResetting(true);
    try {
      await cancelActiveJobs();
      await resetScenarios();
      markAllActiveScenarioErrorsFixed();
      setActiveErrors([]);
      toast.success("Demo workload reset", {
        description: "You can trigger the same scenario again.",
      });
    } catch (err) {
      toast.error("Could not reset the demo workload", {
        description:
          err instanceof ApiError ? err.message : "Unexpected error.",
      });
    } finally {
      setResetting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Trigger an Error"
        description="Choose from 25 common Kubernetes failure modes to generate a controlled failure in the demo workload. The error will appear in your Error Queue where you can diagnose and fix it."
      />

      {activeErrors.length > 0 ? (
        <ActiveErrorBanner
          errors={activeErrors}
          className="mb-6"
          onReset={() => void resetDemo()}
          resetting={resetting}
        />
      ) : null}

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-56" />
          ))}
        </div>
      ) : !scenarios || scenarios.length === 0 ? (
        <EmptyState
          icon={FlaskConical}
          title="No scenarios available"
          description="The scenario service returned an empty catalogue."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {scenarios.map((scenario) => (
            <Card key={scenario.scenario_id}>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <CategoryBadge category={scenario.category} />
                  {scenario.severity ? (
                    <SeverityBadge severity={scenario.severity} />
                  ) : null}
                </div>
                <CardTitle className="text-base">{scenario.name}</CardTitle>
                <CardDescription className="font-mono text-xs">
                  {scenario.scenario_id}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1 space-y-3">
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {scenario.description}
                </p>
              </CardContent>
              <CardFooter>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setConfirmScenario(scenario)}
                  aria-label={`Trigger ${scenario.name}`}
                >
                  <Zap />
                  Trigger Error
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={confirmScenario !== null}
        onOpenChange={(open) => {
          if (!open && !applying) setConfirmScenario(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Trigger &ldquo;{confirmScenario?.name}&rdquo;?</DialogTitle>
            <DialogDescription>
              This will intentionally modify the demo Kubernetes workload and
              cause a failure. You will be able to diagnose the failure from the
              Error Queue.
            </DialogDescription>
          </DialogHeader>
          {confirmScenario ? (
            <div className="bg-muted/40 space-y-2 rounded-md border p-3 text-sm">
              <p className="font-medium">{confirmScenario.name}</p>
              <p className="text-muted-foreground text-xs">
                {confirmScenario.scenario_id}
              </p>
              <p className="text-muted-foreground text-xs">
                {confirmScenario.description}
              </p>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmScenario(null)}
              disabled={applying}
            >
              Cancel
            </Button>
            <Button onClick={onApplyConfirm} disabled={applying}>
              {applying ? (
                <>
                  <LoaderCircle className="animate-spin" />
                  Triggering…
                </>
              ) : (
                <>
                  <Zap />
                  Trigger Error
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
