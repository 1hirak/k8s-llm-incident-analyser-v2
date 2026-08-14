"use client";

import { useState } from "react";
import { Check, CircleAlert, ClipboardList, LoaderCircle, Terminal, Wrench } from "lucide-react";
import { toast } from "sonner";

import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ApiError,
  approveRemediation,
  createRemediation,
  rejectRemediation,
  resetScenarios,
} from "@/lib/api";
import {
  markAllActiveScenarioErrorsFixed,
  updateErrorQueueItem,
} from "@/lib/error-queue";
import type { ErrorQueueItem, IncidentReport } from "@/types";

type FixPhase = "review" | "applying" | "success" | "error";

export function ApplyFixDialog({
  item,
  report,
  open,
  onOpenChange,
  onFixed,
}: {
  item: ErrorQueueItem | null;
  report?: IncidentReport | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFixed: () => void;
}) {
  const [phase, setPhase] = useState<FixPhase>("review");
  const [error, setError] = useState<string | null>(null);
  const [copiedAll, setCopiedAll] = useState(false);

  if (!item) return null;

  const currentItem = item;
  const isDemo = item.source === "scenario";
  const commands = report?.recommended_commands ?? [];
  const actions = report?.recommended_actions ?? [];
  const suggestedFix = report?.suggested_fix ?? "No fix suggestion available.";

  function resetState() {
    setPhase("review");
    setError(null);
    setCopiedAll(false);
  }

  function handleOpenChange(open: boolean) {
    if (!open) resetState();
    onOpenChange(open);
  }

  async function applyDemoFix() {
    setPhase("applying");
    setError(null);
    try {
      await resetScenarios();
      markAllActiveScenarioErrorsFixed();
      setPhase("success");
      onFixed();
      toast.success("Fix applied", {
        description: "The demo workload has been restored.",
      });
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to apply the fix.";
      setError(message);
      setPhase("error");
    }
  }

  async function applyApprovedFix() {
    const action = actions[0];
    if (!action) return;
    setPhase("applying");
    setError(null);
    try {
      const proposal = await createRemediation({
        action,
        requested_by: "dashboard-operator",
      });
      const preview = proposal.dry_run_output
        ? `\n\nServer-side dry-run:\n${proposal.dry_run_output.slice(0, 3000)}`
        : "";
      if (!window.confirm(`Review the dry-run and approve this change?${preview}`)) {
        await rejectRemediation(proposal.remediation_id, {
          approved_by: "dashboard-operator",
          confirm: false,
        });
        setPhase("review");
        return;
      }
      const result = await approveRemediation(proposal.remediation_id, {
        approved_by: "dashboard-operator",
        confirm: true,
      });
      if (result.status !== "applied") {
        throw new Error(result.error ?? "Kubernetes did not apply the remediation.");
      }
      setPhase("success");
      onFixed();
      toast.success("Fix applied", {
        description: "The approved Kubernetes change passed rollout verification.",
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to apply the fix.",
      );
      setPhase("error");
    }
  }

  function markManuallyFixed() {
    updateErrorQueueItem(currentItem.id, {
      status: "fixed",
      fixedAt: new Date().toISOString(),
    });
    setPhase("success");
    onFixed();
    toast.success("Fix applied", {
      description: "The incident has been marked as fixed.",
    });
  }

  async function copyAllCommands() {
    if (commands.length === 0) return;
    try {
      await navigator.clipboard.writeText(commands.join("\n\n"));
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2000);
    } catch {
      // Clipboard unavailable — no-op.
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {phase === "success" ? (
              <Check className="size-5 text-emerald-400" />
            ) : (
              <Wrench className="size-5" />
            )}
            {phase === "success"
              ? "Fix applied"
              : isDemo
                ? "Apply recommended fix?"
                : "Review recommended fix"}
          </DialogTitle>
          <DialogDescription>
            {phase === "success"
              ? "The workload has been restored."
              : "Review the diagnosis before taking action."}
          </DialogDescription>
        </DialogHeader>

        {phase === "review" || phase === "applying" || phase === "error" ? (
          <div className="space-y-5">
            <div className="space-y-2">
              <h4 className="text-sm font-medium">Diagnosis</h4>
              <p className="text-muted-foreground text-sm leading-relaxed">
                {report?.incident_summary ?? "No diagnosis summary available."}
              </p>
            </div>

            <div className="space-y-2">
              <h4 className="text-sm font-medium">Recommended fix</h4>
              <p className="text-sm leading-relaxed">{suggestedFix}</p>
            </div>

            {commands.length > 0 ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="flex items-center gap-2 text-sm font-medium">
                    <Terminal className="text-muted-foreground size-4" />
                    Recommended commands
                  </h4>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={copyAllCommands}
                    disabled={phase === "applying"}
                  >
                    {copiedAll ? <Check className="size-4" /> : null}
                    Copy all
                  </Button>
                </div>
                <div className="space-y-2">
                  {commands.map((command, index) => (
                    <div
                      key={index}
                      className="bg-muted/40 flex items-start gap-2 rounded-md border p-3"
                    >
                      <code className="flex-1 font-mono text-xs leading-relaxed break-all">
                        {command}
                      </code>
                      <CopyButton text={command} />
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {actions.length > 0 ? (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
                A typed remediation action is available. The backend will run a
                server-side dry-run and require your approval before changing the
                cluster.
              </div>
            ) : null}

            {isDemo ? (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-amber-400">
                <CircleAlert className="mt-0.5 size-4 shrink-0" />
                <p className="text-sm leading-relaxed">
                  This demo incident was created by the fault-injection system.
                  Applying the fix will restore the demo workload to its healthy
                  baseline and mark all active demo incidents as fixed.
                </p>
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-amber-400">
                <CircleAlert className="mt-0.5 size-4 shrink-0" />
                <p className="text-sm leading-relaxed">
                  This is a real or manually diagnosed incident. Commands are
                  provided for review and must be run by an operator with
                  cluster access.
                </p>
              </div>
            )}

            {error ? (
              <div
                role="alert"
                className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400"
              >
                {error}
              </div>
            ) : null}
          </div>
        ) : null}

        {phase === "success" ? (
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-4">
              <Check className="mt-0.5 size-5 text-emerald-400" />
              <div>
                <p className="font-medium text-emerald-400">Fix applied</p>
                <p className="text-muted-foreground text-sm">
                  {isDemo
                    ? "The demo workload has been restored."
                    : "The incident has been marked as fixed."}
                </p>
              </div>
            </div>
            {report?.human_verification_steps &&
            report.human_verification_steps.length > 0 ? (
              <div className="space-y-2">
                <h4 className="flex items-center gap-2 text-sm font-medium">
                  <ClipboardList className="text-muted-foreground size-4" />
                  Verification steps
                </h4>
                <ul className="space-y-2">
                  {report.human_verification_steps.map((step, index) => (
                    <li
                      key={index}
                      className="text-muted-foreground text-sm leading-relaxed"
                    >
                      {step}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          {phase === "success" ? (
            <Button onClick={() => handleOpenChange(false)}>Done</Button>
          ) : isDemo ? (
            <>
              <Button
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={phase === "applying"}
              >
                Cancel
              </Button>
              <Button
                onClick={applyDemoFix}
                disabled={phase === "applying"}
              >
                {phase === "applying" ? (
                  <>
                    <LoaderCircle className="animate-spin" />
                    Applying…
                  </>
                ) : (
                  <>
                    <Wrench />
                    Apply Fix
                  </>
                )}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={phase === "applying"}
              >
                Cancel
              </Button>
              {actions.length > 0 ? (
                <Button
                  onClick={applyApprovedFix}
                  disabled={phase === "applying"}
                >
                  {phase === "applying" ? (
                    <>
                      <LoaderCircle className="animate-spin" />
                      Checking and applying…
                    </>
                  ) : (
                    <>
                      <Wrench />
                      Dry-run & Apply Fix
                    </>
                  )}
                </Button>
              ) : commands.length > 0 ? (
                <Button
                  variant="secondary"
                  onClick={copyAllCommands}
                  disabled={phase === "applying"}
                >
                  {copiedAll ? <Check className="size-4" /> : null}
                  Copy Fix Commands
                </Button>
              ) : null}
              <Button
                onClick={markManuallyFixed}
                disabled={phase === "applying"}
              >
                I Applied the Fix
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
