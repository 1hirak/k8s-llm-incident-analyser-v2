import re

from k8s_llm_shared import AnalysisExplanation, EvidenceItem, EvidencePackage, IncidentReport

from app.llm.base import BaseLLMProvider


def _signals(package: EvidencePackage) -> list[str]:
    combined = " ".join(
        (
            package.current_logs,
            package.previous_logs,
            package.pod_status_summary,
            package.k8s_events_filtered,
        )
    ).lower()
    signals: list[str] = []
    for phrase, label in (
        ("oomkilled", "Evidence includes OOMKilled."),
        ("imagepullbackoff", "Evidence includes ImagePullBackOff."),
        ("crashloopbackoff", "Evidence includes CrashLoopBackOff."),
        ("connection refused", "Evidence includes a refused dependency connection."),
        ("readiness probe failed", "Evidence includes a failed readiness probe."),
        ("liveness probe failed", "Evidence includes a failed liveness probe."),
        ("database_url", "Evidence references the DATABASE_URL configuration."),
    ):
        if phrase in combined:
            signals.append(label)
    if package.restart_count:
        signals.append(f"The target has restarted {package.restart_count} time(s).")
    if not signals and package.pod_status_summary:
        signals.append("Pod status was available for the assessment.")
    if not signals and package.current_logs:
        signals.append("Current application logs were available for the assessment.")
    return signals[:5]


def _with_explanation(
    report: IncidentReport, package: EvidencePackage
) -> IncidentReport:
    report.analysis_explanation = AnalysisExplanation(
        rationale=report.likely_root_cause,
        key_signals=_signals(package),
        uncertainty=(
            "This heuristic diagnosis uses bounded, filtered evidence. Review the "
            "cited evidence and verification steps before applying a fix."
        ),
    )
    return report


class MockProvider(BaseLLMProvider):
    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        logs = (package.current_logs + package.previous_logs).lower()
        events = package.k8s_events_filtered.lower()
        status = package.pod_status_summary.lower()
        combined = logs + " " + events + " " + status

        healthy = (
            re.search(r"\bready:\s+true\b", status) is not None
            and package.restart_count == 0
            and not any(
                signal in logs + " " + events
                for signal in (
                    "error",
                    "exception",
                    "failed",
                    "crashloopbackoff",
                    "oomkilled",
                    "imagepullbackoff",
                    "backoff",
                    "refused",
                    "timeout",
                )
            )
        )
        if healthy:
            return _with_explanation(IncidentReport(
                incident_summary=f"No active failure detected in {package.pod_name}",
                likely_root_cause=(
                    "The target is currently running and ready, with no container "
                    "restarts or target-scoped warning events. The available "
                    "evidence does not indicate an active Kubernetes failure."
                ),
                affected_component=package.pod_name,
                failure_category="unknown",
                severity="low",
                confidence=0.95,
                active_error=False,
                supporting_evidence=[
                    EvidenceItem(
                        source="pod_status",
                        pod=package.pod_name,
                        evidence=package.pod_status_summary[:200] or "(no pod status)",
                    )
                ],
                suggested_fix="No remediation is recommended while the target remains healthy.",
                recommended_commands=[],
                human_verification_steps=[
                    "Continue monitoring the target for new warning events or restarts."
                ],
            ), package)

        if "database_url" in logs:
            category, cause = (
                "config",
                "The application cannot complete its database-dependent startup "
                "because the DATABASE_URL environment variable is missing. "
                "Without that connection string, the process cannot initialise "
                "its database configuration and the pod is likely to restart.",
            )
        elif "connection refused" in combined:
            category, cause = (
                "dependency",
                "The application is trying to reach a dependent service, but the "
                "connection is being refused. The dependency is unavailable or "
                "not listening at the configured address, so the application "
                "cannot complete its startup or request handling.",
            )
        elif "oomkilled" in combined or (
            "memory" in logs and "killed" in combined
        ):
            category, cause = (
                "resource",
                "Kubernetes terminated the container after it exceeded its "
                "configured memory limit. The OOMKilled status indicates that "
                "the process used more memory than the pod allocation, which "
                "causes the workload to restart.",
            )
        elif "imagepullbackoff" in combined or (
            "image" in status and "pull" in status
        ):
            category, cause = (
                "image",
                "Kubernetes cannot start the pod because the referenced container "
                "image cannot be pulled. The ImagePullBackOff state shows that "
                "image retrieval has failed repeatedly, commonly because of an "
                "incorrect image reference or unavailable registry credentials.",
            )
        elif "readiness probe failed" in combined:
            category, cause = (
                "probe",
                "The container is running, but its readiness probe is failing. "
                "Kubernetes therefore keeps the pod out of service because the "
                "application is not yet responding as ready on the configured "
                "health endpoint.",
            )
        elif "liveness probe failed" in combined:
            category, cause = (
                "probe",
                "The container is failing its liveness probe, which tells "
                "Kubernetes that the running process is no longer healthy. "
                "Kubernetes will restart the container until the health check "
                "succeeds consistently.",
            )
        elif "containercannotrun" in combined or (
            "crashloopbackoff" in combined and "executable file not found" in combined
        ):
            category, cause = (
                "crash",
                "The container cannot start because its configured executable "
                "was not found in the image. Kubernetes retries the failed start, "
                "which produces the observed CrashLoopBackOff state.",
            )
        elif "runtimeerror" in combined and (
            "startup" in combined or "crashloopbackoff" in status
        ):
            category, cause = (
                "crash",
                "The application raises a runtime error during startup before it "
                "can become healthy. Each failed startup causes Kubernetes to "
                "restart the container, resulting in the CrashLoopBackOff state.",
            )
        elif "crashloopbackoff" in combined:
            category, cause = (
                "crash",
                "The container is repeatedly starting and then exiting, so "
                "Kubernetes has placed it in CrashLoopBackOff. The available "
                "evidence confirms repeated failures but does not identify a "
                "more specific application-level cause.",
            )
        else:
            category, cause = (
                "unknown",
                "The collected logs, pod status, and Kubernetes events do not "
                "contain enough specific evidence to identify the failure "
                "mechanism. Additional logs or recent events are needed before "
                "a reliable root-cause explanation can be made.",
            )

        return _with_explanation(IncidentReport(
            incident_summary=f"[MOCK] Failure detected in {package.pod_name}",
            likely_root_cause=cause,
            affected_component=package.pod_name,
            failure_category=category,
            severity="medium",
            confidence=0.5,
            supporting_evidence=[
                EvidenceItem(
                    source="pod_log",
                    pod=package.pod_name,
                    evidence=package.current_logs[:200] or "(no logs)",
                )
            ],
            suggested_fix="[MOCK] Investigate the reported root cause.",
            recommended_commands=[
                f"kubectl describe pod -n {package.namespace} {package.pod_name}"
            ],
            human_verification_steps=[
                "Check the logs manually",
                "Verify environment variables",
            ],
        ), package)
