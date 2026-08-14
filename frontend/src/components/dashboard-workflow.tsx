"use client";

import { useEffect, useState } from "react";

import { ActiveErrorBanner } from "@/components/active-error-banner";
import { WorkflowStepper } from "@/components/workflow-stepper";
import {
  loadErrorQueue,
  type ErrorQueueItem,
} from "@/lib/error-queue";

export function DashboardWorkflow() {
  const [queue, setQueue] = useState<ErrorQueueItem[]>([]);

  useEffect(() => {
    setQueue(loadErrorQueue());

    function onStorage(event: StorageEvent) {
      if (event.key === "k8s-incident-analyser.error-queue.v1") {
        setQueue(loadErrorQueue());
      }
    }

    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const activeErrors = queue.filter(
    (item) => item.source === "scenario" && item.status !== "fixed",
  );
  const activeError = activeErrors[0] ?? null;
  const needsDiagnosisCount = queue.filter(
    (item) => item.status === "triggered" || item.status === "diagnosis_failed",
  ).length;
  const readyToFixCount = queue.filter(
    (item) => item.status === "diagnosed",
  ).length;

  let activeStep: "trigger" | "diagnose" | "fix" = "trigger";
  if (activeError) {
    activeStep =
      activeError.status === "diagnosed" ? "fix" : "diagnose";
  } else if (needsDiagnosisCount > 0) {
    activeStep = "diagnose";
  } else if (readyToFixCount > 0) {
    activeStep = "fix";
  }

  return (
    <div className="space-y-6">
      {activeErrors.length > 0 ? <ActiveErrorBanner errors={activeErrors} /> : null}
      <WorkflowStepper
        activeStep={activeStep}
        needsDiagnosisCount={needsDiagnosisCount}
        readyToFixCount={readyToFixCount}
        activeError={activeError}
      />
    </div>
  );
}
