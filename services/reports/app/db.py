"""SQLite persistence layer for reports-svc.

Implements the database contract (contracts/database/schema.sql). This
service is the single writer to the SQLite file; WAL mode allows
concurrent reads. The schema is applied on startup (idempotent
CREATE IF NOT EXISTS — no migration framework in v1).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

from k8s_llm_shared import (
    IncidentReport,
    JobState,
    LatencyPoint,
    ReportSummary,
    SaveJobRequest,
    StatsResponse,
)

def _schema_path() -> str:
    """Return the resolved schema SQL path.

    In Docker the ``SCHEMA_PATH`` env var is set by the Dockerfile
    (``/app/schema.sql``). In local dev it defaults to the repo-relative
    path; the fallback is *inside* the function so it is never evaluated
    when the env var is present (avoiding ``parents[3]`` overflow when
    the file lives at ``/app/app/db.py`` inside the container).
    """
    env = os.environ.get("SCHEMA_PATH")
    if env:
        return env
    # Local dev fallback — only reached when running outside Docker
    return str(
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "database"
        / "schema.sql"
    )

_RANGE_MODIFIERS = {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def _to_iso8601(sqlite_ts: str | None) -> str | None:
    """Convert SQLite datetime('now') output to ISO 8601 with Z suffix."""
    if sqlite_ts is None:
        return None
    return sqlite_ts.replace(" ", "T") + "Z"


class ReportsDB:
    """Thread-safe wrapper around the SQLite reports database."""

    def __init__(self, path: str):
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        schema = Path(_schema_path()).read_text()
        with self._lock:
            self._conn.executescript(schema)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def save_report(
        self,
        report: IncidentReport,
        namespace: str,
        pod_name: str,
        job_id: str,
    ) -> str:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO incidents (
                    incident_id, namespace, pod_name, failure_category,
                    severity, confidence, incident_summary,
                    likely_root_cause, affected_component, suggested_fix,
                    report_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.incident_id,
                    namespace,
                    pod_name,
                    report.failure_category,
                    report.severity,
                    report.confidence,
                    report.incident_summary,
                    report.likely_root_cause,
                    report.affected_component,
                    report.suggested_fix,
                    report.model_dump_json(),
                    report.created_at,
                    report.created_at,
                ),
            )
            # Link the producing job to this report
            self._conn.execute(
                "UPDATE analysis_jobs SET incident_id = ? WHERE job_id = ?",
                (report.incident_id, job_id),
            )
            self._conn.commit()
        return report.incident_id

    def list_reports(
        self,
        *,
        namespace: str | None = None,
        pod_name: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ReportSummary], int]:
        clauses, params = [], []
        if namespace:
            clauses.append("namespace = ?")
            params.append(namespace)
        if pod_name:
            clauses.append("pod_name = ?")
            params.append(pod_name)
        if category:
            clauses.append("failure_category = ?")
            params.append(category)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        count = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM incidents {where}", params
        ).fetchone()["c"]
        rows = self._conn.execute(
            f"""
            SELECT incident_id, namespace, pod_name, failure_category,
                   severity, confidence, incident_summary, created_at
            FROM incidents {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        items = [
            ReportSummary(
                incident_id=row["incident_id"],
                namespace=row["namespace"],
                pod_name=row["pod_name"],
                failure_category=row["failure_category"],
                severity=row["severity"],
                confidence=row["confidence"],
                incident_summary=row["incident_summary"],
                created_at=_to_iso8601(row["created_at"]) or "",
            )
            for row in rows
        ]
        return items, count

    def get_report(self, incident_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT report_json FROM incidents WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["report_json"])

    # ------------------------------------------------------------------
    # Jobs (durable snapshot of Redis state)
    # ------------------------------------------------------------------

    def upsert_job(self, job: SaveJobRequest) -> str:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO analysis_jobs (
                    job_id, namespace, pod_name, status, stage,
                    incident_id, latency_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    stage = excluded.stage,
                    incident_id = COALESCE(
                        excluded.incident_id, analysis_jobs.incident_id
                    ),
                    latency_ms = COALESCE(
                        excluded.latency_ms, analysis_jobs.latency_ms
                    ),
                    error = excluded.error
                """,
                (
                    job.job_id,
                    job.namespace,
                    job.pod_name,
                    job.status,
                    job.stage,
                    job.incident_id,
                    job.latency_ms,
                    job.error,
                ),
            )
            self._conn.commit()
        return job.job_id

    def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[JobState], int]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        count = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM analysis_jobs {where}", params
        ).fetchone()["c"]
        rows = self._conn.execute(
            f"""
            SELECT job_id, namespace, pod_name, status, stage,
                   incident_id, latency_ms, error, created_at, updated_at
            FROM analysis_jobs {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        items = [
            JobState(
                job_id=row["job_id"],
                namespace=row["namespace"],
                pod_name=row["pod_name"],
                status=row["status"],
                stage=row["stage"],
                incident_id=row["incident_id"],
                latency_ms=row["latency_ms"],
                error=row["error"],
                created_at=_to_iso8601(row["created_at"]) or "",
                updated_at=_to_iso8601(row["updated_at"]) or "",
            )
            for row in rows
        ]
        return items, count

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self, range_param: str = "7d") -> StatsResponse:
        modifier = _RANGE_MODIFIERS.get(range_param, "-7 days")

        total = self._conn.execute(
            "SELECT COUNT(*) AS c FROM incidents"
        ).fetchone()["c"]
        reports_24h = self._conn.execute(
            "SELECT COUNT(*) AS c FROM incidents "
            "WHERE created_at >= datetime('now', '-1 day')"
        ).fetchone()["c"]
        mean_latency = self._conn.execute(
            "SELECT AVG(latency_ms) AS m FROM analysis_jobs "
            "WHERE status = 'done' AND latency_ms IS NOT NULL "
            "AND created_at >= datetime('now', ?)",
            (modifier,),
        ).fetchone()["m"]
        mean_confidence = self._conn.execute(
            "SELECT AVG(confidence) AS m FROM incidents "
            "WHERE created_at >= datetime('now', ?)",
            (modifier,),
        ).fetchone()["m"]
        category_rows = self._conn.execute(
            "SELECT failure_category, COUNT(*) AS c FROM incidents "
            "GROUP BY failure_category"
        ).fetchall()
        latency_rows = self._conn.execute(
            "SELECT created_at, latency_ms FROM analysis_jobs "
            "WHERE status = 'done' AND latency_ms IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

        return StatsResponse(
            total_reports=total,
            reports_24h=reports_24h,
            mean_latency_ms=round(mean_latency or 0.0, 2),
            mean_confidence=round(mean_confidence or 0.0, 4),
            category_counts={row["failure_category"]: row["c"] for row in category_rows},
            latency_series=[
                LatencyPoint(
                    timestamp=_to_iso8601(row["created_at"]) or "",
                    latency_ms=row["latency_ms"],
                )
                for row in reversed(latency_rows)
            ],
        )
