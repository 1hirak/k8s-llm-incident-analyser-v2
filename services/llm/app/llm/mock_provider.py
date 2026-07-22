from k8s_llm_shared import EvidenceItem, EvidencePackage, IncidentReport

from app.llm.base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    async def analyse(self, package: EvidencePackage) -> IncidentReport:
        logs = (package.current_logs + package.previous_logs).lower()
        events = package.k8s_events_filtered.lower()
        status = package.pod_status_summary.lower()
        combined = logs + " " + events + " " + status

        if "database_url" in logs:
            category, cause = "config", "Missing DATABASE_URL environment variable"
        elif "connection refused" in combined:
            category, cause = "dependency", "Dependent service is unreachable"
        elif "oomkilled" in combined or (
            "memory" in logs and "killed" in combined
        ):
            category, cause = "resource", "Container exceeded memory limit (OOMKilled)"
        elif "imagepullbackoff" in combined or (
            "image" in status and "pull" in status
        ):
            category, cause = "image", "Kubernetes cannot pull the container image"
        elif "readiness probe failed" in combined:
            category, cause = "probe", "Readiness probe is failing"
        elif "liveness probe failed" in combined:
            category, cause = "probe", "Liveness probe is failing"
        elif "containercannotrun" in combined or (
            "crashloopbackoff" in combined and "executable file not found" in combined
        ):
            category, cause = "crash", "Container cannot start (executable not found)"
        elif "runtimeerror" in combined and (
            "startup" in combined or "crashloopbackoff" in status
        ):
            category, cause = "crash", "Application raised a runtime error on startup"
        elif "crashloopbackoff" in combined:
            category, cause = "crash", "Container is in CrashLoopBackOff"
        else:
            category, cause = "unknown", "Unable to determine root cause from evidence"

        return IncidentReport(
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
        )
