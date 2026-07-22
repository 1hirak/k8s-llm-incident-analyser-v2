"""Pipeline coordinator — orchestrates collector → processor → llm → reports.

Implements the job lifecycle from contracts/database/redis_schema.md §3.
Every stage transition is written to Redis and published to the job's
event channel for SSE fanout. Terminal states (done/failed) are archived
to reports-svc as durable snapshots.
"""

from __future__ import annotations

import time

import httpx
import structlog
from k8s_llm_shared import (
    EvidencePackage,
    IncidentReport,
    RawEvidence,
    SaveJobRequest,
)

from app.store import JobStore

log = structlog.get_logger()


class Pipeline:
    def __init__(
        self,
        *,
        store: JobStore,
        http: httpx.AsyncClient,
        collector_url: str,
        processor_url: str,
        llm_url: str,
        reports_url: str,
        timeout_seconds: int = 120,
    ):
        self._store = store
        self._http = http
        self._collector_url = collector_url.rstrip("/")
        self._processor_url = processor_url.rstrip("/")
        self._llm_url = llm_url.rstrip("/")
        self._reports_url = reports_url.rstrip("/")
        self._timeout = timeout_seconds

    async def _archive_job(self, job: SaveJobRequest) -> None:
        """Best-effort durable snapshot; archival failure never fails a job."""
        try:
            resp = await self._http.post(
                f"{self._reports_url}/jobs",
                json=job.model_dump(),
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as e:
            log.warning("job_archive_failed", job_id=job.job_id, error=str(e))

    async def _llm_stage_label(self) -> str:
        """Fetch provider/model from llm-svc for a human-readable stage."""
        try:
            resp = await self._http.get(f"{self._llm_url}/health", timeout=5)
            data = resp.json()
            provider = data.get("provider")
            model = data.get("model")
            if provider and model:
                return f"Calling {provider} {model}"
            if provider:
                return f"Calling {provider}"
        except Exception:
            pass
        return "Calling LLM provider"

    async def run(self, job_id: str, namespace: str, pod_name: str) -> None:
        start = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - start) * 1000)

        try:
            # Stage 1: collect
            await self._store.transition(
                job_id, "collecting",
                f"Collecting evidence for {namespace}/{pod_name}",
            )
            raw = await self._call_collect(namespace, pod_name)

            # Stage 2: process
            await self._store.transition(
                job_id, "processing", "Filtering logs and redacting secrets"
            )
            package = await self._call_process(raw)

            # Stage 3: llm
            await self._store.transition(
                job_id, "llm_call", await self._llm_stage_label()
            )
            report = await self._call_analyse(package)

            # Stage 4: persist
            await self._store.transition(job_id, "persisting", "Saving report")
            incident_id = await self._call_save_report(
                report, raw.namespace, raw.pod_name, job_id
            )

            # Done
            latency = elapsed_ms()
            await self._store.complete(job_id, incident_id, latency, report)
            await self._archive_job(
                SaveJobRequest(
                    job_id=job_id,
                    namespace=namespace,
                    pod_name=pod_name,
                    status="done",
                    incident_id=incident_id,
                    latency_ms=latency,
                )
            )
            log.info(
                "pipeline_complete", job_id=job_id,
                incident_id=incident_id, latency_ms=latency,
            )
        except Exception as e:
            latency = elapsed_ms()
            error = str(e) or type(e).__name__
            log.error("pipeline_failed", job_id=job_id, error=error)
            await self._store.fail(job_id, error, latency)
            await self._archive_job(
                SaveJobRequest(
                    job_id=job_id,
                    namespace=namespace,
                    pod_name=pod_name,
                    status="failed",
                    error=error[:500],
                    latency_ms=latency,
                )
            )

    # ------------------------------------------------------------------
    # Downstream calls (raise RuntimeError with context on failure)
    # ------------------------------------------------------------------

    async def _call_collect(self, namespace: str, pod_name: str) -> RawEvidence:
        data = await self._post(
            f"{self._collector_url}/collect",
            {"namespace": namespace, "pod_name": pod_name},
            stage="collector",
            timeout=60,
        )
        return RawEvidence(**data)

    async def _call_process(self, raw: RawEvidence) -> EvidencePackage:
        data = await self._post(
            f"{self._processor_url}/process",
            raw.model_dump(),
            stage="processor",
            timeout=30,
        )
        return EvidencePackage(**data)

    async def _call_analyse(self, package: EvidencePackage) -> IncidentReport:
        data = await self._post(
            f"{self._llm_url}/analyse",
            package.model_dump(),
            stage="llm",
            timeout=60,
        )
        return IncidentReport(**data)

    async def _call_save_report(
        self, report: IncidentReport, namespace: str, pod_name: str, job_id: str
    ) -> str:
        data = await self._post(
            f"{self._reports_url}/reports",
            {
                "report": report.model_dump(),
                "namespace": namespace,
                "pod_name": pod_name,
                "job_id": job_id,
            },
            stage="reports",
            timeout=30,
        )
        return data["incident_id"]

    async def _post(
        self, url: str, payload: dict, *, stage: str, timeout: float
    ) -> dict:
        try:
            resp = await self._http.post(url, json=payload, timeout=timeout)
        except httpx.TimeoutException as e:
            raise RuntimeError(f"{stage}-svc timed out after {timeout}s") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"{stage}-svc unreachable: {e}") from e
        if resp.status_code != 200 and resp.status_code != 201:
            detail = resp.text[:300]
            raise RuntimeError(
                f"{stage}-svc returned {resp.status_code}: {detail}"
            )
        return resp.json()
