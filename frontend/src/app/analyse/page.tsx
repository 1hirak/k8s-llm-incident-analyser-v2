"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  CircleCheck,
  CircleX,
  LoaderCircle,
  Play,
  RotateCcw,
  ScanSearch,
} from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { PipelineTimeline } from "@/components/pipeline-timeline";
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
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { ApiError, createJob } from "@/lib/api";
import { streamJob } from "@/lib/sse";
import { formatLatency } from "@/lib/utils";
import type { JobStatus, SseDoneEvent, SseFailedEvent } from "@/types";

type Phase = "idle" | "running" | "done" | "failed";

export default function AnalysePage() {
  const [namespace, setNamespace] = useState("demo");
  const [podName, setPodName] = useState("demo-app");
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState<JobStatus>("queued");
  const [stage, setStage] = useState<string | null>(null);
  const [doneEvent, setDoneEvent] = useState<SseDoneEvent | null>(null);
  const [failedEvent, setFailedEvent] = useState<SseFailedEvent | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const closeStreamRef = useRef<(() => void) | null>(null);

  // Close any open EventSource when the page unmounts.
  useEffect(() => {
    return () => {
      closeStreamRef.current?.();
    };
  }, []);

  function reset() {
    closeStreamRef.current?.();
    closeStreamRef.current = null;
    setPhase("idle");
    setStatus("queued");
    setStage(null);
    setDoneEvent(null);
    setFailedEvent(null);
    setSubmitError(null);
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase === "running") return;

    setSubmitError(null);
    setDoneEvent(null);
    setFailedEvent(null);
    setStatus("queued");
    setStage(null);

    let jobId: string;
    try {
      const job = await createJob({
        namespace: namespace.trim(),
        pod_name: podName.trim(),
      });
      jobId = job.job_id;
    } catch (error) {
      setSubmitError(
        error instanceof ApiError
          ? error.message
          : "Failed to create the analysis job.",
      );
      return;
    }

    setPhase("running");
    closeStreamRef.current?.();
    closeStreamRef.current = streamJob(
      jobId,
      (event) => {
        if (event.type === "stage") {
          setStatus(event.data.status);
          setStage(event.data.stage ?? null);
        } else if (event.type === "done") {
          setStatus("done");
          setDoneEvent(event.data);
          setPhase("done");
        } else {
          setFailedEvent(event.data);
          setPhase("failed");
        }
      },
      () => {
        // Transport-level error before a terminal event arrived.
        setFailedEvent((previous) =>
          previous ?? {
            event: "failed",
            job_id: jobId,
            status: "failed",
            error:
              "Lost connection to the event stream before the job finished.",
            latency_ms: 0,
          },
        );
        setPhase((previous) => (previous === "running" ? "failed" : previous));
      },
    );
  }

  const running = phase === "running";

  return (
    <>
      <PageHeader
        title="Analyse"
        description="Run a live LLM failure analysis against a Kubernetes pod"
      />

      <div className="grid items-start gap-6 lg:grid-cols-[380px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>New analysis</CardTitle>
            <CardDescription>
              Targets a pod by name — a deployment name works too, it is
              resolved via label selector.
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
                <Input
                  id="namespace"
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                  placeholder="demo"
                  required
                  disabled={running}
                />
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="pod_name"
                  className="text-muted-foreground text-sm font-medium"
                >
                  Pod name
                </label>
                <Input
                  id="pod_name"
                  value={podName}
                  onChange={(e) => setPodName(e.target.value)}
                  placeholder="demo-app"
                  required
                  disabled={running}
                />
              </div>
              {submitError ? (
                <Alert variant="destructive">
                  <CircleX />
                  <AlertTitle>Could not start analysis</AlertTitle>
                  <AlertDescription>{submitError}</AlertDescription>
                </Alert>
              ) : null}
              <Button
                type="submit"
                className="w-full"
                disabled={running || !namespace.trim() || !podName.trim()}
              >
                {running ? (
                  <>
                    <LoaderCircle className="animate-spin" />
                    Analysing…
                  </>
                ) : (
                  <>
                    <Play />
                    Run analysis
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        {phase === "idle" ? (
          <EmptyState
            icon={ScanSearch}
            title="No analysis running"
            description="Submit a pod on the left to watch the analysis pipeline live — evidence collection, processing, the LLM call and persistence."
          />
        ) : (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Pipeline</CardTitle>
                <CardDescription className="font-mono text-xs">
                  {namespace.trim()}/{podName.trim()}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <PipelineTimeline
                  status={status}
                  failed={phase === "failed"}
                  stage={stage}
                />
              </CardContent>
            </Card>

            {phase === "done" && doneEvent ? (
              <Card className="border-emerald-500/40 bg-emerald-500/5">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <CircleCheck className="size-5 text-emerald-400" />
                    <CardTitle>Analysis complete</CardTitle>
                  </div>
                  <CardDescription>
                    Finished in {formatLatency(doneEvent.latency_ms)}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    {doneEvent.failure_category ? (
                      <CategoryBadge category={doneEvent.failure_category} />
                    ) : null}
                    {doneEvent.severity ? (
                      <SeverityBadge severity={doneEvent.severity} />
                    ) : null}
                  </div>
                  <Separator />
                  <div className="flex flex-wrap gap-2">
                    <Button asChild>
                      <Link href={`/reports/${doneEvent.incident_id}`}>
                        View report
                      </Link>
                    </Button>
                    <Button variant="outline" onClick={reset}>
                      <RotateCcw />
                      Run another analysis
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ) : null}

            {phase === "failed" && failedEvent ? (
              <Alert variant="destructive">
                <CircleX />
                <AlertTitle>Analysis failed</AlertTitle>
                <AlertDescription className="gap-3">
                  <span>
                    {failedEvent.error}
                    {failedEvent.latency_ms
                      ? ` (after ${formatLatency(failedEvent.latency_ms)})`
                      : ""}
                  </span>
                  <Button variant="outline" size="sm" onClick={reset}>
                    <RotateCcw />
                    Run another analysis
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
