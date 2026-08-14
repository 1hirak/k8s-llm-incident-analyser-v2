"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CircleCheck, CircleX, Play, RotateCcw, ScanSearch } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { DiagnosisProgress } from "@/components/diagnosis-progress";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { useDiagnosisJob } from "@/hooks/use-diagnosis-job";
import { useLLMConfig } from "@/hooks/use-llm-config";
import { ApiError, listTargets } from "@/lib/api";
import { formatLatency } from "@/lib/utils";
import type { TargetKind, TargetOption } from "@/types";

const TARGET_KINDS: { value: TargetKind; label: string }[] = [
  { value: "Pod", label: "Pod" },
  { value: "Deployment", label: "Deployment" },
  { value: "ReplicaSet", label: "ReplicaSet" },
  { value: "StatefulSet", label: "StatefulSet" },
  { value: "DaemonSet", label: "DaemonSet" },
  { value: "Job", label: "Job" },
  { value: "CronJob", label: "CronJob" },
  { value: "Service", label: "Service" },
  { value: "Namespace", label: "Namespace" },
  { value: "Node", label: "Node" },
];

export default function AnalysePage() {
  const [targetKind, setTargetKind] = useState<TargetKind>("Pod");
  const [namespace, setNamespace] = useState("demo");
  const [targetName, setTargetName] = useState("");
  const [namespaces, setNamespaces] = useState<TargetOption[]>([]);
  const [targets, setTargets] = useState<TargetOption[]>([]);
  const [targetsLoading, setTargetsLoading] = useState(false);
  const [targetError, setTargetError] = useState<string | null>(null);
  const {
    phase,
    status,
    stage,
    doneEvent,
    failedEvent,
    submitError,
    activity,
    startDiagnosis,
    reset,
  } = useDiagnosisJob();
  const llmConfig = useLLMConfig();

  const clusterScoped = targetKind === "Namespace" || targetKind === "Node";

  useEffect(() => {
    let cancelled = false;
    listTargets("Namespace")
      .then((result) => {
        if (!cancelled) {
          setNamespaces(result.items);
          if (result.items.some((item) => item.name === "demo")) {
            setNamespace("demo");
          } else if (result.items[0]) {
            setNamespace(result.items[0].name);
          }
        }
      })
      .catch(() => {
        if (!cancelled) setTargetError("Unable to load Kubernetes namespaces.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setTargetsLoading(true);
    setTargetError(null);
    setTargetName("");
    listTargets(targetKind, clusterScoped ? undefined : namespace)
      .then((result) => {
        if (!cancelled) {
          setTargets(result.items);
          setTargetName(result.items[0]?.name ?? "");
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTargets([]);
          setTargetError(
            error instanceof ApiError
              ? error.message
              : "Unable to load Kubernetes targets.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setTargetsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [clusterScoped, namespace, targetKind]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase === "running" || phase === "reconnecting") return;

    event.currentTarget.checkValidity();
    const selectedNamespace = clusterScoped ? "all" : namespace.trim();
    const podName = targetName.trim();
    if (!selectedNamespace || !podName) return;

    await startDiagnosis(selectedNamespace, podName, targetKind);
  }

  const running = phase === "running" || phase === "reconnecting";

  return (
    <>
      <PageHeader
        title="Diagnose Target"
        description="Diagnose pods, workloads, services, namespaces, and nodes using live Kubernetes evidence."
      />

      <div className="grid items-start gap-6 lg:grid-cols-[380px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>New diagnosis</CardTitle>
            <CardDescription>
              Select a resource. Workloads are resolved to their related pods so
              the analysis can combine resource status, events, and logs.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                <label
                  htmlFor="namespace"
                  className="text-muted-foreground text-sm font-medium"
                >
                  Namespace
                </label>
                <Select
                  value={namespace}
                  onValueChange={setNamespace}
                  disabled={running || clusterScoped}
                >
                  <SelectTrigger id="namespace">
                    <SelectValue placeholder="Select namespace" />
                  </SelectTrigger>
                  <SelectContent>
                    {namespaces.map((item) => (
                      <SelectItem key={item.name} value={item.name}>
                        {item.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="target_kind"
                  className="text-muted-foreground text-sm font-medium"
                >
                  Resource type
                </label>
                <Select
                  value={targetKind}
                  onValueChange={(value) => setTargetKind(value as TargetKind)}
                  disabled={running}
                >
                  <SelectTrigger id="target_kind">
                    <SelectValue placeholder="Select resource type" />
                  </SelectTrigger>
                  <SelectContent>
                    {TARGET_KINDS.map((kind) => (
                      <SelectItem key={kind.value} value={kind.value}>
                        {kind.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="target_name"
                  className="text-muted-foreground text-sm font-medium"
                >
                  Resource name
                </label>
                <Select
                  value={targetName}
                  onValueChange={setTargetName}
                  disabled={running || targetsLoading || targets.length === 0}
                >
                  <SelectTrigger id="target_name">
                    <SelectValue
                      placeholder={
                        targetsLoading ? "Loading targets…" : "Select resource"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {targets.map((target) => (
                      <SelectItem key={`${target.kind}-${target.name}`} value={target.name}>
                        {target.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">
                  {clusterScoped
                    ? "Cluster-scoped target"
                    : `${targets.length} target${targets.length === 1 ? "" : "s"} in ${namespace}`}
                </p>
              </div>
              {targetError ? (
                <Alert variant="destructive">
                  <CircleX />
                  <AlertTitle>Target discovery failed</AlertTitle>
                  <AlertDescription>{targetError}</AlertDescription>
                </Alert>
              ) : null}
              {submitError ? (
                <Alert variant="destructive">
                  <CircleX />
                  <AlertTitle>Could not start diagnosis</AlertTitle>
                  <AlertDescription>{submitError}</AlertDescription>
                </Alert>
              ) : null}
              <Button
                type="submit"
                className="w-full"
                disabled={running || !targetName || targetsLoading}
              >
                {running ? (
                  <>
                    <div className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    Diagnosing…
                  </>
                ) : (
                  <>
                    <Play />
                    Run diagnosis
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        {phase === "idle" ? (
          <EmptyState
            icon={ScanSearch}
            title="No diagnosis running"
            description="Submit a pod on the left to watch the diagnosis pipeline live — evidence collection, processing, the LLM call and persistence."
          />
        ) : (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Diagnosis pipeline</CardTitle>
                <CardDescription className="font-mono text-xs">
                  Diagnosis in progress
                </CardDescription>
              </CardHeader>
              <CardContent>
                <DiagnosisProgress
                  status={status}
                  stage={stage}
                  reconnecting={phase === "reconnecting"}
                  failed={phase === "failed"}
                  llmConfig={llmConfig}
                  activity={activity}
                />
              </CardContent>
            </Card>

            {phase === "done" && doneEvent ? (
              <Card className="border-emerald-500/40 bg-emerald-500/5">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <CircleCheck className="size-5 text-emerald-400" />
                    <CardTitle>Diagnosis complete</CardTitle>
                  </div>
                  <CardDescription>
                    Finished in {formatLatency(doneEvent.latency_ms)}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {doneEvent.active_error ? (
                    <div className="flex flex-wrap items-center gap-2">
                      {doneEvent.failure_category ? (
                        <CategoryBadge category={doneEvent.failure_category} />
                      ) : null}
                      {doneEvent.severity ? (
                        <SeverityBadge severity={doneEvent.severity} />
                      ) : null}
                    </div>
                  ) : (
                    <p className="text-sm font-medium text-emerald-400">
                      No active error detected. The target is currently healthy.
                    </p>
                  )}
                  <Separator />
                  <div className="flex flex-wrap gap-2">
                    <Button asChild>
                      <Link href={`/reports/${doneEvent.incident_id}`}>
                        View report
                      </Link>
                    </Button>
                    <Button variant="outline" onClick={reset}>
                      <RotateCcw />
                      Run another diagnosis
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ) : null}

            {phase === "failed" && failedEvent ? (
              <Alert variant="destructive">
                <CircleX />
                <AlertTitle>Diagnosis failed</AlertTitle>
                <AlertDescription className="gap-3">
                  <span>
                    {failedEvent.error}
                    {failedEvent.latency_ms
                      ? ` (after ${formatLatency(failedEvent.latency_ms)})`
                      : ""}
                  </span>
                  <Button variant="outline" size="sm" onClick={reset}>
                    <RotateCcw />
                    Run another diagnosis
                  </Button>
                </AlertDescription>
              </Alert>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}
