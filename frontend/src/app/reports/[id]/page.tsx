import { notFound } from "next/navigation";
import {
  ClipboardList,
  Cpu,
  Search,
  Square,
  Terminal,
  Wrench,
} from "lucide-react";

import { ConfidenceMeter } from "@/components/confidence-meter";
import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { EvidenceCard } from "@/components/evidence-card";
import { PageHeader } from "@/components/page-header";
import { CategoryBadge, SeverityBadge } from "@/components/status-badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, getReport } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import type { IncidentReport } from "@/types";

export default async function ReportDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let report: IncidentReport;
  try {
    report = await getReport(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    return (
      <>
        <PageHeader title="Incident report" description={`Report ${id}`} />
        <ErrorState
          message={
            error instanceof Error ? error.message : "Failed to load report."
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Incident report"
        description={`${report.incident_id} · ${formatDateTime(report.created_at)}`}
      />

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={report.severity} />
            <CategoryBadge category={report.failure_category} />
          </div>
          <CardTitle className="text-xl leading-snug">
            {report.incident_summary}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-w-xs space-y-1">
            <p className="text-muted-foreground text-xs font-medium">
              LLM confidence
            </p>
            <ConfidenceMeter value={report.confidence} />
          </div>
        </CardContent>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Search className="text-muted-foreground size-4" />
              <CardTitle className="text-base">Likely root cause</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed">{report.likely_root_cause}</p>
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

      <Card className="mt-4">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Wrench className="text-muted-foreground size-4" />
            <CardTitle className="text-base">Suggested fix</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed">{report.suggested_fix}</p>
        </CardContent>
      </Card>

      <Tabs defaultValue="evidence" className="mt-6">
        <TabsList>
          <TabsTrigger value="evidence">
            Evidence ({report.supporting_evidence.length})
          </TabsTrigger>
          <TabsTrigger value="commands">
            Commands ({report.recommended_commands.length})
          </TabsTrigger>
          <TabsTrigger value="verification">
            Verification ({report.human_verification_steps.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="evidence" className="mt-4">
          <div className="grid gap-4 lg:grid-cols-2">
            {report.supporting_evidence.map((item, index) => (
              <EvidenceCard key={index} item={item} />
            ))}
          </div>
        </TabsContent>

        <TabsContent value="commands" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Terminal className="text-muted-foreground size-4" />
                <CardTitle className="text-base">Recommended commands</CardTitle>
              </div>
              <CardDescription>
                Review before running — these modify cluster state.
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

        <TabsContent value="verification" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <ClipboardList className="text-muted-foreground size-4" />
                <CardTitle className="text-base">
                  Human verification steps
                </CardTitle>
              </div>
              <CardDescription>
                Confirm the fix manually before closing the incident.
              </CardDescription>
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
    </>
  );
}
