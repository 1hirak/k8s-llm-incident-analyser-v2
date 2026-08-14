import {
  AlertTriangle,
  BrainCircuit,
  Database,
  Eye,
  ListChecks,
  ShieldCheck,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AnalysisExplanation } from "@/types";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2">
      <p className="text-[10px] font-medium tracking-[0.12em] text-white/40 uppercase">
        {label}
      </p>
      <p className="mt-1 text-sm font-medium text-white/80">{value}</p>
    </div>
  );
}

export function AnalysisTransparency({
  explanation,
  providerName,
  model,
}: {
  explanation?: AnalysisExplanation | null;
  providerName?: string;
  model?: string | null;
}) {
  const summary = explanation?.input_summary;

  return (
    <Card className="border-cyan-300/20 bg-cyan-300/[0.025]">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 rounded-lg border border-cyan-300/20 bg-cyan-300/10 p-2 text-cyan-200">
              <BrainCircuit className="size-4" />
            </span>
            <div>
              <CardTitle className="text-base">How this diagnosis was formed</CardTitle>
              <CardDescription className="mt-1 max-w-2xl">
                A concise, evidence-backed audit trail. This is an operator-facing
                explanation, not hidden model reasoning.
              </CardDescription>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-1 text-[10px] font-medium text-emerald-200">
            <Eye className="size-3" />
            Inspectable
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {explanation ? (
          <>
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.7fr)]">
              <section className="space-y-2" aria-labelledby="assessment-heading">
                <div className="flex items-center gap-2">
                  <ListChecks className="size-4 text-cyan-200" />
                  <h3 id="assessment-heading" className="text-sm font-medium">
                    Evidence-backed assessment
                  </h3>
                </div>
                <p className="text-sm leading-6 text-white/70">
                  {explanation.rationale || "No structured rationale was returned."}
                </p>
              </section>

              <section className="space-y-2" aria-labelledby="signals-heading">
                <div className="flex items-center gap-2">
                  <Database className="size-4 text-cyan-200" />
                  <h3 id="signals-heading" className="text-sm font-medium">
                    Observed signals
                  </h3>
                </div>
                {explanation.key_signals.length > 0 ? (
                  <ul className="space-y-2">
                    {explanation.key_signals.map((signal, index) => (
                      <li key={`${signal}-${index}`} className="flex gap-2 text-xs leading-5 text-white/60">
                        <span className="mt-2 size-1.5 shrink-0 rounded-full bg-cyan-200/70" />
                        <span>{signal}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs leading-5 text-white/50">
                    No individual signals were returned. Review the cited evidence below.
                  </p>
                )}
              </section>
            </div>

            <section className="rounded-lg border border-amber-300/15 bg-amber-300/[0.06] p-3" aria-labelledby="uncertainty-heading">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-200" />
                <div>
                  <h3 id="uncertainty-heading" className="text-sm font-medium text-amber-100">
                    Uncertainty and operator checks
                  </h3>
                  <p className="mt-1 text-xs leading-5 text-amber-100/70">
                    {explanation.uncertainty || "Complete the human verification steps before applying remediation."}
                  </p>
                </div>
              </div>
            </section>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Input"
                value={summary ? "Redacted evidence" : "Evidence excerpts"}
              />
              <Stat
                label="Log lines"
                value={summary
                  ? `${summary.current_log_lines} current · ${summary.previous_log_lines} previous`
                  : "See evidence tab"}
              />
              <Stat
                label="Cluster signals"
                value={summary
                  ? `${summary.has_pod_status ? "status" : "no status"} · ${summary.has_kubernetes_events ? "events" : "no events"}`
                  : "See evidence tab"}
              />
              <Stat
                label="Safety"
                value={summary?.redaction_applied
                  ? `${summary.redaction_count} value(s) redacted`
                  : "Redaction not reported"}
              />
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-white/[0.07] pt-4 text-xs text-white/45">
              <span className="inline-flex items-center gap-1.5">
                <ShieldCheck className="size-3.5 text-emerald-300" />
                API keys and unredacted cluster data are not shown here
              </span>
              {providerName ? <span>Provider: {providerName}</span> : null}
              {model && model !== "Free mock classifier" ? <span>Model: {model}</span> : null}
            </div>
          </>
        ) : (
          <p className="text-sm leading-6 text-muted-foreground">
            This report was created before structured transparency data was available.
            Use the root cause and cited evidence below, then complete the human
            verification steps before applying a fix.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
