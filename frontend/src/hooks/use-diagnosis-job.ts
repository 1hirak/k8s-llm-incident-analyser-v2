"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, createJob, getJob } from "@/lib/api";
import { logger } from "@/lib/logger";
import { streamJob } from "@/lib/sse";
import type {
  JobStatus,
  SseDoneEvent,
  SseFailedEvent,
  TargetKind,
} from "@/types";

export type DiagnosisPhase =
  | "idle"
  | "running"
  | "reconnecting"
  | "done"
  | "failed";

/**
 * One timestamped line of the behind-the-scenes activity trace, derived
 * from the real SSE events received for the job.
 */
export type ActivityEntry = {
  kind: "stage" | "done" | "failed";
  status: JobStatus;
  /** Stage label (e.g. "Calling openai gpt-4o-mini") or error message. */
  detail: string;
  /** Client-side receive time (ms epoch). */
  at: number;
  latencyMs?: number;
};

export type UseDiagnosisJobOptions = {
  onDone?: (event: SseDoneEvent) => void;
  onFailed?: (event: SseFailedEvent) => void;
};

const RECONNECT_INTERVAL_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 15;

/**
 * Manages a single diagnosis job lifecycle: creation, SSE streaming,
 * reconnection on transport errors, and terminal state handling.
 */
export function useDiagnosisJob(options: UseDiagnosisJobOptions = {}) {
  const [phase, setPhase] = useState<DiagnosisPhase>("idle");
  const [status, setStatus] = useState<JobStatus>("queued");
  const [stage, setStage] = useState<string | null>(null);
  const [doneEvent, setDoneEvent] = useState<SseDoneEvent | null>(null);
  const [failedEvent, setFailedEvent] = useState<SseFailedEvent | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);

  const jobIdRef = useRef<string | null>(null);
  const closeStreamRef = useRef<(() => void) | null>(null);
  const terminalRef = useRef(false);
  const generationRef = useRef(0);

  const appendActivity = useCallback((entry: ActivityEntry) => {
    setActivity((prev) => {
      // The SSE stream replays the current stage on (re)subscribe — drop
      // consecutive duplicates so the trace stays clean.
      const last = prev[prev.length - 1];
      if (
        last &&
        last.kind === entry.kind &&
        last.status === entry.status &&
        last.detail === entry.detail
      ) {
        return prev;
      }
      return [...prev, entry];
    });
  }, []);

  const reset = useCallback(() => {
    generationRef.current += 1;
    closeStreamRef.current?.();
    closeStreamRef.current = null;
    jobIdRef.current = null;
    terminalRef.current = false;
    setPhase("idle");
    setStatus("queued");
    setStage(null);
    setDoneEvent(null);
    setFailedEvent(null);
    setSubmitError(null);
    setActivity([]);
  }, []);

  const handleDone = useCallback(
    (event: SseDoneEvent) => {
      terminalRef.current = true;
      closeStreamRef.current?.();
      closeStreamRef.current = null;
      setStatus("done");
      setDoneEvent(event);
      setPhase("done");
      appendActivity({
        kind: "done",
        status: "done",
        detail: "Diagnosis complete",
        at: Date.now(),
        latencyMs: event.latency_ms,
      });
      options.onDone?.(event);
    },
    [options, appendActivity],
  );

  const handleFailed = useCallback(
    (event: SseFailedEvent) => {
      terminalRef.current = true;
      closeStreamRef.current?.();
      closeStreamRef.current = null;
      setStatus("failed");
      setFailedEvent(event);
      setPhase("failed");
      appendActivity({
        kind: "failed",
        status: "failed",
        detail: event.error,
        at: Date.now(),
        latencyMs: event.latency_ms,
      });
      options.onFailed?.(event);
    },
    [options, appendActivity],
  );

  const subscribe = useCallback(
    (jobId: string) => {
      closeStreamRef.current?.();
      closeStreamRef.current = streamJob(
        jobId,
        (event) => {
          if (jobIdRef.current !== jobId) return;
          if (event.type === "stage") {
            setStatus(event.data.status);
            setStage(event.data.stage ?? null);
            appendActivity({
              kind: "stage",
              status: event.data.status,
              detail: event.data.stage ?? "",
              at: Date.now(),
            });
          } else if (event.type === "done") {
            handleDone(event.data);
          } else {
            handleFailed(event.data);
          }
        },
        () => {
          // Transport-level interruption. Do not treat as a terminal failure
          // immediately; switch to reconnecting and poll the job status.
          if (!terminalRef.current && jobIdRef.current === jobId) {
            logger.warn({ msg: "diagnosis_stream_interrupted", jobId });
            setPhase("reconnecting");
          }
        },
      );
    },
    [handleDone, handleFailed, appendActivity],
  );

  const startDiagnosis = useCallback(
    async (
      namespace: string,
      podName: string,
      targetKind: TargetKind = "Pod",
    ): Promise<string | null> => {
      reset();
      const generation = generationRef.current;
      setPhase("running");

      let jobId: string;
      try {
        const job = await createJob({
          namespace: namespace.trim(),
          pod_name: podName.trim(),
          target_kind: targetKind,
        });
        jobId = job.job_id;
      } catch (error) {
        if (generation !== generationRef.current) return null;
        const message =
          error instanceof ApiError
            ? error.message
            : "Failed to create the diagnosis job.";
        setSubmitError(message);
        setPhase("failed");
        setFailedEvent({
          event: "failed",
          job_id: "",
          status: "failed",
          error: message,
          latency_ms: 0,
        });
        options.onFailed?.({
          event: "failed",
          job_id: "",
          status: "failed",
          error: message,
          latency_ms: 0,
        });
        return null;
      }

      if (generation !== generationRef.current) return null;

      jobIdRef.current = jobId;
      terminalRef.current = false;
      setStatus("queued");
      setStage(null);
      subscribe(jobId);
      return jobId;
    },
    [options, reset, subscribe],
  );

  // Reconnection fallback: poll job status when the SSE stream is interrupted.
  useEffect(() => {
    if (phase !== "reconnecting") return;

    let attempts = 0;
    let cancelled = false;
    const jobId = jobIdRef.current;
    if (!jobId) return;

    async function poll() {
      if (cancelled || !jobId) return;
      attempts += 1;

      try {
        const job = await getJob(jobId);
        if (cancelled) return;

        setStatus(job.status);
        setStage(job.stage ?? null);

        if (job.status === "done" && job.incident_id) {
          handleDone({
            event: "done",
            job_id: job.job_id,
            status: "done",
            incident_id: job.incident_id,
            failure_category: undefined,
            severity: undefined,
            active_error: true,
            latency_ms: job.latency_ms ?? undefined,
          });
          return;
        }

        if (job.status === "failed") {
          handleFailed({
            event: "failed",
            job_id: job.job_id,
            status: "failed",
            error: job.error ?? "Diagnosis failed.",
            latency_ms: job.latency_ms ?? undefined,
          });
          return;
        }

        if (attempts >= MAX_RECONNECT_ATTEMPTS) {
          handleFailed({
            event: "failed",
            job_id: jobId,
            status: "failed",
            error:
              "Connection interrupted and could not be re-established before the job completed.",
            latency_ms: 0,
          });
          return;
        }
      } catch (error) {
        if (cancelled) return;
        logger.warn({
          msg: "diagnosis_reconnect_poll_failed",
          jobId,
          error: error instanceof Error ? error.message : String(error),
        });
        if (attempts >= MAX_RECONNECT_ATTEMPTS) {
          handleFailed({
            event: "failed",
            job_id: jobId,
            status: "failed",
            error:
              "Connection interrupted and could not be re-established before the job completed.",
            latency_ms: 0,
          });
        }
      }
    }

    poll();
    const intervalId = setInterval(poll, RECONNECT_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [phase, handleDone, handleFailed]);

  // Clean up the stream on unmount.
  useEffect(() => {
    return () => {
      closeStreamRef.current?.();
    };
  }, []);

  return {
    phase,
    status,
    stage,
    doneEvent,
    failedEvent,
    submitError,
    activity,
    startDiagnosis,
    reset,
  };
}
