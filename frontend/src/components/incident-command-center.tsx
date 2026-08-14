"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Check,
  Layers3,
  Radar,
  ShieldCheck,
  Sparkles,
  TimerReset,
  Wrench,
  Zap,
} from "lucide-react";

import { ActiveErrorBanner } from "@/components/active-error-banner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { loadErrorQueue, type ErrorQueueItem } from "@/lib/error-queue";
import { cn, formatRelativeTime } from "@/lib/utils";

const WORKFLOW = [
  { label: "Incident intake", icon: Zap },
  { label: "Error queue", icon: Layers3 },
  { label: "Diagnose", icon: Radar },
  { label: "Apply fix", icon: Wrench },
  { label: "Fixed", icon: ShieldCheck },
] as const;

function stepState(activeError: ErrorQueueItem | null, index: number) {
  if (!activeError) return index === 0 ? "current" : "upcoming";
  if (activeError.status === "fixed") return "complete";
  if (index === 0 || index === 1) return "complete";
  if (index === 2) {
    return activeError.status === "triggered" || activeError.status === "diagnosis_failed"
      ? "current"
      : "complete";
  }
  if (index === 3) return activeError.status === "diagnosed" ? "current" : "upcoming";
  return "upcoming";
}

export function IncidentCommandCenter() {
  const [queue, setQueue] = useState<ErrorQueueItem[]>([]);
  const refreshQueue = useCallback(() => setQueue(loadErrorQueue()), []);

  useEffect(() => {
    refreshQueue();

    function onStorage(event: StorageEvent) {
      if (event.key === "k8s-incident-analyser.error-queue.v1") refreshQueue();
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [refreshQueue]);

  const activeError = useMemo(
    () => queue.find((item) => item.source === "scenario" && item.status !== "fixed") ?? null,
    [queue],
  );
  const activeErrors = useMemo(
    () => queue.filter((item) => item.source === "scenario" && item.status !== "fixed"),
    [queue],
  );
  const openCount = queue.filter((item) => item.status !== "fixed").length;
  const fixedCount = queue.filter((item) => item.status === "fixed").length;
  const currentStep = WORKFLOW.findIndex((_, index) => stepState(activeError, index) === "current");

  return (
    <div className="space-y-8">
      <header className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
        <div className="max-w-2xl">
          <h1 className="text-gradient text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">
            Incident command center
          </h1>
          <p className="mt-3 max-w-xl text-base leading-7 text-muted-foreground">
            Monitor incidents and move them through intake, diagnosis, remediation, and verification.
          </p>
        </div>
        <Link
          href="/analyse"
          className="group inline-flex items-center gap-2 self-start rounded-lg border border-white/10 bg-white/[0.04] px-4 py-2.5 text-sm font-medium transition hover:border-white/20 hover:bg-white/[0.08] lg:self-auto"
        >
          Start a diagnosis
          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="metric-tile">
          <span className="metric-icon text-amber-300"><Zap className="size-4" /></span>
          <span><strong>{openCount}</strong><small>open incidents</small></span>
        </div>
        <div className="metric-tile">
          <span className="metric-icon text-emerald-300"><Check className="size-4" /></span>
          <span><strong>{fixedCount}</strong><small>fixed this session</small></span>
        </div>
        <div className="metric-tile">
          <span className="metric-icon text-cyan-300"><TimerReset className="size-4" /></span>
          <span><strong>~2 min</strong><small>average resolution</small></span>
        </div>
      </div>

      <section className="workflow-rail" aria-label="Incident workflow">
        {WORKFLOW.map((step, index) => {
          const state = stepState(activeError, index);
          const Icon = step.icon;
          return (
            <div key={step.label} className="flex min-w-0 flex-1 items-center">
              <div className="flex min-w-0 items-center gap-3">
                <span className={cn("workflow-dot", state === "complete" && "workflow-dot-complete", state === "current" && "workflow-dot-current")}>
                  {state === "complete" ? <Check className="size-4" /> : <Icon className="size-4" />}
                </span>
                <span className={cn("hidden text-xs font-semibold sm:block", state === "current" ? "text-foreground" : "text-muted-foreground")}>
                  {step.label}
                </span>
              </div>
              {index < WORKFLOW.length - 1 ? <span className={cn("workflow-line", index < currentStep && "workflow-line-complete")} /> : null}
            </div>
          );
        })}
      </section>

      {activeErrors.length > 0 ? (
        <ActiveErrorBanner errors={activeErrors} />
      ) : (
        <div className="flex items-start gap-3 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.045] px-4 py-3.5 text-sm">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-300" />
          <p className="text-muted-foreground"><span className="font-medium text-emerald-200">Cluster ready.</span> No demo fault is currently active.</p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Investigation workspace</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm leading-6 text-muted-foreground">
            <p>Run a diagnosis against a Kubernetes workload, inspect the evidence, and review the generated incident report.</p>
            <div className="flex flex-wrap gap-2">
              <Button asChild><Link href="/analyse">Run diagnosis <ArrowRight /></Link></Button>
              <Button asChild variant="outline"><Link href="/errors">View error queue</Link></Button>
            </div>
          </CardContent>
        </Card>

        <aside className="space-y-4">
          <Card className="overflow-hidden border-cyan-300/15 bg-cyan-300/[0.035]">
            <CardHeader className="border-b border-white/[0.06] pb-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="eyebrow text-cyan-200/70">Next handoff</p>
                  <CardTitle className="mt-1 text-base">{activeError ? "Work the active error" : "Ready for investigation"}</CardTitle>
                </div>
                <span className="rounded-lg bg-cyan-300/10 p-2 text-cyan-200"><Sparkles className="size-4" /></span>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              {activeError ? (
                <>
                  <div>
                    <p className="font-medium">{activeError.scenarioName ?? "Active incident"}</p>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">{activeError.namespace}/{activeError.podName}</p>
                    <p className="mt-3 text-xs text-muted-foreground">Triggered {formatRelativeTime(activeError.triggeredAt)}</p>
                  </div>
                  <Button asChild className="w-full"><Link href={`/errors?id=${activeError.id}`}>Open incident <ArrowRight /></Link></Button>
                </>
              ) : (
                <p className="text-sm leading-6 text-muted-foreground">Start a diagnosis from the workspace, or review incidents already waiting for attention.</p>
              )}
            </CardContent>
          </Card>
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-4">
            <p className="eyebrow">Operator note</p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">Use the diagnosis workflow for real workloads. Demo scenarios remain available separately for controlled testing.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
