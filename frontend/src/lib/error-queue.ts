import { logger } from "./logger";
import type { FailureCategory, Severity } from "@/types";

export type ErrorQueueItemStatus =
  | "triggered"
  | "diagnosing"
  | "diagnosed"
  | "diagnosis_failed"
  | "fixing"
  | "fixed";

export type ErrorQueueItem = {
  id: string;
  source: "scenario" | "detected";
  scenarioId?: string;
  scenarioName?: string;
  namespace: string;
  podName: string;
  category?: FailureCategory;
  severity?: Severity;
  triggeredAt: string;
  status: ErrorQueueItemStatus;
  jobId?: string;
  incidentId?: string;
  diagnosisError?: string;
  fixedAt?: string;
};

const STORAGE_KEY = "k8s-incident-analyser.error-queue.v1";

function isClient(): boolean {
  return typeof window !== "undefined";
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function parseQueue(data: string | null): ErrorQueueItem[] {
  if (!data) return [];
  try {
    const parsed = JSON.parse(data) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidErrorQueueItem);
  } catch {
    logger.error({ msg: "error_queue_parse_failed" });
    return [];
  }
}

function isValidErrorQueueItem(value: unknown): value is ErrorQueueItem {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<ErrorQueueItem>;
  return (
    typeof item.id === "string" &&
    (item.source === "scenario" || item.source === "detected") &&
    typeof item.namespace === "string" &&
    typeof item.podName === "string" &&
    typeof item.triggeredAt === "string" &&
    typeof item.status === "string" &&
    [
      "triggered",
      "diagnosing",
      "diagnosed",
      "diagnosis_failed",
      "fixing",
      "fixed",
    ].includes(item.status)
  );
}

export function loadErrorQueue(): ErrorQueueItem[] {
  if (!isClient()) return [];
  return parseQueue(localStorage.getItem(STORAGE_KEY));
}

export function saveErrorQueue(queue: ErrorQueueItem[]): void {
  if (!isClient()) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
  } catch (err) {
    logger.error({
      msg: "error_queue_save_failed",
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

export function addErrorQueueItem(
  item: Omit<ErrorQueueItem, "id" | "triggeredAt">,
): ErrorQueueItem {
  const queue = loadErrorQueue();
  const newItem: ErrorQueueItem = {
    ...item,
    id: generateId(),
    triggeredAt: new Date().toISOString(),
  };
  saveErrorQueue([newItem, ...queue]);
  return newItem;
}

export function updateErrorQueueItem(
  id: string,
  updates: Partial<Omit<ErrorQueueItem, "id">>,
): ErrorQueueItem | null {
  const queue = loadErrorQueue();
  const index = queue.findIndex((item) => item.id === id);
  if (index === -1) return null;
  const updated = { ...queue[index], ...updates };
  queue[index] = updated;
  saveErrorQueue(queue);
  return updated;
}

export function getErrorQueueItem(id: string): ErrorQueueItem | null {
  return loadErrorQueue().find((item) => item.id === id) ?? null;
}

/**
 * Returns the first active demo scenario error, if any.
 * The queue can contain multiple active scenario errors; callers that need
 * the complete set should filter loadErrorQueue() directly.
 */
export function getActiveScenarioError(): ErrorQueueItem | null {
  return getActiveScenarioErrors()[0] ?? null;
}

export function getActiveScenarioErrors(): ErrorQueueItem[] {
  return loadErrorQueue().filter(
    (item) => item.source === "scenario" && item.status !== "fixed",
  );
}

export function hasActiveScenarioError(): boolean {
  return getActiveScenarioError() !== null;
}

export function markAllActiveScenarioErrorsFixed(): number {
  const queue = loadErrorQueue();
  const fixedAt = new Date().toISOString();
  let updatedCount = 0;
  const updatedQueue = queue.map((item) => {
    if (item.source !== "scenario" || item.status === "fixed") return item;
    updatedCount += 1;
    return { ...item, status: "fixed" as const, fixedAt };
  });
  if (updatedCount > 0) saveErrorQueue(updatedQueue);
  return updatedCount;
}

export function clearErrorQueue(): void {
  saveErrorQueue([]);
}
