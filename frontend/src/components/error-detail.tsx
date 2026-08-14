"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  ClipboardList,
  Cpu,
  Play,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Terminal,
  Wrench,
} from "lucide-react";

import { ConfidenceMeter } from "@/components/confidence-meter";
import { CopyButton } from "@/components/copy-button";
import { AnalysisTransparency } from "@/components/analysis-transparency";
import { DiagnosisProgress } from "@/components/diagnosis-progress";
import { ErrorState } from "@/components/error-state";
import { EvidenceCard } from "@/components/evidence-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import { ApiError, getReport } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useLLMConfig } from "@/hooks/use-llm-config";
import type {
  ActivityEntry,
  DiagnosisPhase,
} from "@/hooks/use-diagnosis-job";
import type {
  ErrorQueueItem,
  IncidentReport,
  JobStatus,
  SseFailedEvent,
} from "@/types";

export function ErrorDetail({
  item,
  onApplyFix,
  onStartDiagnosis,
  onMarkCompleted,
  diagnosisPhase,
  jobStatus,
  stage,
  failedEvent,
  activity,
}: {
  item: ErrorQueueItem;
  onApplyFix: (item: ErrorQueueItem) => void;
  onStartDiagnosis: (item: ErrorQueueItem) => void;
  onMarkCompleted: (item: ErrorQueueItem) => void;
  diagnosisPhase?: DiagnosisPhase;
  jobStatus?: JobStatus;
  stage?: string | null;
  failedEvent?: SseFailedEvent | null;
  activity?: ActivityEntry[];
}) {
  const [report, setReport] = useState<IncidentReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const llmConfig = useLLMConfig();
  const analysisSource = useMemo(() => {
    if (report?.provider) {
      const providerName =
        llmConfig.providers.find((p) => p.id === report.provider)?.name ??
        report.provider;
      return {
        isMock: report.provider === "mock",
        providerName,
        model: report.model ?? "",
      };
    }
    return {
      isMock: llmConfig.isMock,
      providerName: llmConfig.providerName,
      model: llmConfig.model,
    };
  }, [report, llmConfig]);

  useEffect(() => {
    if (!item.incidentId) {
      setReport(null);
      return;
    }
    let cancelled = false;
    setReportLoading(true);
    setReportError(null);
    getReport(item.incidentId)
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch((err) => {
        if (!cancelled) {
          setReportError(
            err instanceof ApiError ? err.message : "Failed to load report.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setReportLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item.incidentId]);

  function startDiagnosisForItem() {
    onStartDiagnosis(item);
  }

  const phase = diagnosisPhase ?? "idle";
  const status = jobStatus ?? "queued";

  if (item.status === "triggered" || item.status === "diagnosis_failed") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            {item.status === "diagnosis_failed"
              ? "Diagnosis failed"
              : "Ready to diagnose"}
          </CardTitle>
          <CardDescription>
            {item.namespace}/{item.podName}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {item.status === "diagnosis_failed" && (item.diagnosisError || failedEvent) ? (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
              {item.diagnosisError ?? failedEvent?.error}
            </div>
          ) : null}
          <Button onClick={startDiagnosisForItem} className="w-full sm:w-auto">
            {item.status === "diagnosis_failed" ? (
              <>
                <RotateCcw />
                Retry Diagnosis
              </>
            ) : (
              <>
                <Play />
                Diagnose Error
              </>
            )}
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (item.status === "diagnosing") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Diagnosing…</CardTitle>
          <CardDescription>
            {item.namespace}/{item.podName}
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
          {phase === "failed" && (item.diagnosisError || failedEvent) ? (
            <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
              {item.diagnosisError ?? failedEvent?.error}
            </div>
          ) : null}
          {item.status === "diagnosing" ? (
            <Button
              onClick={startDiagnosisForItem}
              variant="outline"
              className="mt-4 w-full sm:w-auto"
            >
              <RotateCcw />
              {phase === "failed" ? "Retry Diagnosis" : "Re-diagnose"}
            </Button>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  if (item.status === "fixing") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Applying fix…</CardTitle>
          <CardDescription>Restoring the demo workload.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 text-muted-foreground">
            <div className="size-5 animate-spin rounded-full border-2 border-accent-indigo border-t-transparent" />
            <span className="text-sm">Please wait…</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (reportLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </CardContent>
      </Card>
    );
  }

  if (reportError) {
    return <ErrorState message={reportError} />;
  }

  if (!report) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Diagnosis complete</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            Report details are not available.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card
        className={
          item.status === "fixed"
            ? "border-emerald-500/40 bg-emerald-500/5"
            : undefined
        }
      >
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            {item.status === "fixed" ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
                <Check className="size-3" />
                Fixed
              </span>
            ) : null}
            {report.active_error !== false ? (
              <>
                <SeverityBadge severity={report.severity} />
                <CategoryBadge category={report.failure_category} />
              </>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
                <Check className="size-3" />
                No active error
              </span>
            )}
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
                analysisSource.isMock
                  ? "border-sky-500/40 bg-sky-500/10 text-sky-400"
                  : "border-accent-indigo/40 bg-accent-indigo/10 text-accent-indigo",
              )}
            >
              <Sparkles className="size-3" />
              {report.active_error === false
                ? "Healthy target"
                : analysisSource.isMock
                  ? "Heuristic diagnosis"
                  : "AI-generated diagnosis"}
            </span>
          </div>
          <CardTitle className="text-xl leading-snug">
            {report.incident_summary}
          </CardTitle>
          <CardDescription>
            {report.target_kind}/{report.target_name ?? report.affected_component}
            {report.target_name && report.affected_component !== report.target_name
              ? ` · ${report.affected_component}`
              : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="max-w-xs space-y-1">
              <p className="text-muted-foreground text-xs font-medium">
                Model confidence
              </p>
              <ConfidenceMeter value={report.confidence} />
            </div>
            <p className="max-w-prose text-xs leading-5 text-white/50">
              This report was produced by{" "}
              <span className="font-medium text-white/70">
                {analysisSource.providerName}
              </span>
              {analysisSource.model && analysisSource.model !== "Free mock classifier" ? (
                <>
                  {" "}
                  using model{" "}
                  <span className="font-mono font-medium text-white/70">
                    {analysisSource.model}
                  </span>
                </>
              ) : null}
              . The model only receives redacted cluster evidence; review all
              commands before running them.
            </p>
          </div>
        </CardContent>
      </Card>

      <AnalysisTransparency
        explanation={report.analysis_explanation}
        providerName={analysisSource.providerName}
        model={analysisSource.model}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Search className="text-muted-foreground size-4" />
              <CardTitle className="text-base">Likely root cause</CardTitle>
              <span className="ml-auto inline-flex items-center gap-1 rounded-md border border-accent-indigo/30 bg-accent-indigo/5 px-2 py-0.5 text-[10px] font-medium text-accent-indigo/80">
                <Sparkles className="size-3" />
                AI analysis
              </span>
            </div>
            <CardDescription>
              Why the failure is happening, based on the collected evidence.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed">
              {report.likely_root_cause}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Cpu className="text-muted-foreground size-4" />
              <CardTitle className="text-base">Affected component</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-sm leading-relaxed">
              {report.affected_component}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-accent-indigo/30">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Wrench className="text-accent-indigo size-4" />
            <CardTitle className="text-base">Suggested fix</CardTitle>
            <span className="ml-auto inline-flex items-center gap-1 rounded-md border border-accent-indigo/30 bg-accent-indigo/5 px-2 py-0.5 text-[10px] font-medium text-accent-indigo/80">
              <Sparkles className="size-3" />
              AI recommendation
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed">{report.suggested_fix}</p>
        </CardContent>
      </Card>

      <Tabs defaultValue="commands">
        <TabsList>
          <TabsTrigger value="commands">
            Commands ({report.recommended_commands.length})
          </TabsTrigger>
          <TabsTrigger value="evidence">
            Evidence ({report.supporting_evidence.length})
          </TabsTrigger>
          <TabsTrigger value="verification">
            Verification ({report.human_verification_steps.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="commands" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Terminal className="text-muted-foreground size-4" />
                <CardTitle className="text-base">Recommended commands</CardTitle>
              </div>
              <CardDescription>
                Generated by the LLM from redacted evidence. Review every command
                before running — these modify cluster state.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {report.recommended_commands.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  No commands recommended for this incident.
                </p>
              ) : (
                report.recommended_commands.map((command, index) => (
                  <div
                    key={index}
                    className="bg-muted/40 flex items-start gap-2 rounded-md border p-3"
                  >
                    <code className="flex-1 font-mono text-xs leading-relaxed break-all">
                      {command}
                    </code>
                    <CopyButton text={command} />
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="evidence" className="mt-4">
          <div className="grid gap-4 lg:grid-cols-2">
            {report.supporting_evidence.map((item, index) => (
              <EvidenceCard key={index} item={item} />
            ))}
          </div>
        </TabsContent>

        <TabsContent value="verification" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <ClipboardList className="text-muted-foreground size-4" />
                <CardTitle className="text-base">
                  Human verification steps
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              {report.human_verification_steps.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  No verification steps provided.
                </p>
              ) : (
                <ul className="space-y-3">
                  {report.human_verification_steps.map((step, index) => (
                    <li key={index} className="flex items-start gap-3">
                      <Square className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                      <span className="text-sm leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {item.status === "diagnosed" && report.active_error !== false ? (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => onApplyFix(item)}>
            <Wrench />
            Apply Fix
          </Button>
          <Button
            onClick={() => onMarkCompleted(item)}
            variant="outline"
          >
            <CheckCircle2 />
            Mark as Completed
          </Button>
        </div>
      ) : item.status === "diagnosed" ? (
        <Button onClick={() => onMarkCompleted(item)} variant="outline">
          <CheckCircle2 />
          Mark as Completed
        </Button>
      ) : null}

      {item.incidentId ? (
        <Button asChild variant="outline" className="w-full sm:w-auto">
          <Link href={`/reports/${item.incidentId}`}>Open full report</Link>
        </Button>
      ) : null}
    </div>
  );
}
