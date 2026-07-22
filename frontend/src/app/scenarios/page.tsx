"use client";

import { useCallback, useEffect, useState } from "react";
import { FlaskConical, LoaderCircle, Play, RotateCcw } from "lucide-react";
import { toast } from "sonner";

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
import { ApiError, applyScenario, listScenarios, resetScenarios } from "@/lib/api";
import type { ScenarioSummary } from "@/types";

export default function ScenariosPage() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmScenario, setConfirmScenario] =
    useState<ScenarioSummary | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [applying, setApplying] = useState(false);
  const [resetting, setResetting] = useState(false);

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
  }, [load]);

  async function onApplyConfirm() {
    if (!confirmScenario) return;
    setApplying(true);
    try {
      const res = await applyScenario(confirmScenario.scenario_id);
      toast.success(`Applied ${confirmScenario.name}`, {
        description: res.fault_description ?? "The fault is now live in the cluster.",
      });
      setConfirmScenario(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.warning("A scenario is already applied", {
          description: "Reset the cluster before applying another scenario.",
        });
      } else {
        toast.error("Failed to apply scenario", {
          description:
            err instanceof ApiError ? err.message : "Unexpected error.",
        });
      }
    } finally {
      setApplying(false);
    }
  }

  async function onResetConfirm() {
    setResetting(true);
    try {
      await resetScenarios();
      toast.success("Cluster reset", {
        description: "The demo deployment is back to its healthy baseline.",
      });
      setConfirmReset(false);
    } catch (err) {
      toast.error("Failed to reset cluster", {
        description: err instanceof ApiError ? err.message : "Unexpected error.",
      });
    } finally {
      setResetting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Scenarios"
        description="Fault scenarios for the demo cluster — apply one, then analyse the failing pod"
      >
        <Button
          variant="outline"
          className="border-red-500/40 text-red-400 hover:bg-red-500/10 hover:text-red-400"
          onClick={() => setConfirmReset(true)}
        >
          <RotateCcw />
          Reset cluster
        </Button>
      </PageHeader>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
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
              <CardContent className="flex-1">
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {scenario.description}
                </p>
              </CardContent>
              <CardFooter>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setConfirmScenario(scenario)}
                >
                  <Play />
                  Apply
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
            <DialogTitle>Apply {confirmScenario?.name}?</DialogTitle>
            <DialogDescription>
              This modifies live cluster state — the demo deployment will start
              failing until you reset it. Run an analysis from the Analyse page
              once the pod begins to fail.
            </DialogDescription>
          </DialogHeader>
          {confirmScenario ? (
            <p className="bg-muted/40 rounded-md border p-3 font-mono text-xs">
              {confirmScenario.scenario_id} — {confirmScenario.description}
            </p>
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
                  Applying…
                </>
              ) : (
                "Apply scenario"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmReset}
        onOpenChange={(open) => {
          if (!open && !resetting) setConfirmReset(false);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset cluster?</DialogTitle>
            <DialogDescription>
              Removes any applied fault and re-applies the base manifests. The
              demo deployment returns to its healthy baseline.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmReset(false)}
              disabled={resetting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={onResetConfirm}
              disabled={resetting}
            >
              {resetting ? (
                <>
                  <LoaderCircle className="animate-spin" />
                  Resetting…
                </>
              ) : (
                "Reset cluster"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
