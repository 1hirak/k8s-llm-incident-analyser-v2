import { API_BASE_URL } from "./api";
import { logger } from "./logger";
import type { SseDoneEvent, SseFailedEvent, SseStageEvent } from "@/types";

export type JobStreamEvent =
  | { type: "stage"; data: SseStageEvent }
  | { type: "done"; data: SseDoneEvent }
  | { type: "failed"; data: SseFailedEvent };

function parseMessage<T>(event: Event): T {
  return JSON.parse((event as MessageEvent<string>).data) as T;
}

/**
 * Subscribes to the gateway SSE stream for a job.
 *
 * The stream is closed automatically on `done` / `failed` events.
 * Returns an unsubscribe function — call it on unmount.
 */
export function streamJob(
  jobId: string,
  onEvent: (event: JobStreamEvent) => void,
  onError?: (event: Event) => void,
): () => void {
  const source = new EventSource(
    `${API_BASE_URL}/api/jobs/${jobId}/stream`,
  );

  source.addEventListener("stage", (event) => {
    onEvent({ type: "stage", data: parseMessage<SseStageEvent>(event) });
  });

  source.addEventListener("done", (event) => {
    onEvent({ type: "done", data: parseMessage<SseDoneEvent>(event) });
    source.close();
  });

  source.addEventListener("failed", (event) => {
    const data = parseMessage<SseFailedEvent>(event);
    logger.error({ msg: "sse_pipeline_failed", jobId, ...data });
    onEvent({ type: "failed", data });
    source.close();
  });

  source.onerror = (event) => {
    logger.error({ msg: "sse_connection_error", jobId });
    onError?.(event);
  };

  return () => {
    source.close();
  };
}
