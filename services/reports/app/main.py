"""reports-svc — incident report and job persistence service.

Implements contracts/api/reports.yaml. Owns the SQLite database
(contracts/database/schema.sql); it is the single writer. Other services
access report data via this service's API, never directly.
"""

import os
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException, Query
from k8s_llm_shared import (
    SaveJobRequest,
    SaveReportRequest,
    SaveReportResponse,
    StatsResponse,
)
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.db import ReportsDB

log = structlog.get_logger()

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/reports.db")

app = FastAPI(
    title="reports-svc",
    description="Incident report and analysis job persistence (SQLite)",
    version="0.1.0",
)
add_error_handlers(app)

db = ReportsDB(DATABASE_PATH)


@app.get("/health", tags=["Health"])
def health() -> dict:
    return health_payload("reports-svc")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@app.post(
    "/reports",
    response_model=SaveReportResponse,
    status_code=201,
    tags=["Reports"],
)
def save_report(request: SaveReportRequest) -> SaveReportResponse:
    """Persist a completed IncidentReport and link the producing job."""
    log.info("save_report", incident_id=request.report.incident_id)
    try:
        incident_id = db.save_report(
            request.report, request.namespace, request.pod_name, request.job_id
        )
    except Exception as e:
        log.error("save_report_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Database write failed: {e}"
        ) from e
    return SaveReportResponse(incident_id=incident_id)


@app.get("/reports", tags=["Reports"])
def list_reports(
    namespace: Optional[str] = None,
    pod_name: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, count = db.list_reports(
        namespace=namespace,
        pod_name=pod_name,
        category=category,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [item.model_dump() for item in items],
        "count": count,
        "limit": limit,
        "offset": offset,
    }


@app.get("/reports/{incident_id}", tags=["Reports"])
def get_report(incident_id: str) -> dict:
    report = db.get_report(incident_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


# ---------------------------------------------------------------------------
# Jobs (durable snapshot of Redis state)
# ---------------------------------------------------------------------------


@app.post("/jobs", status_code=201, tags=["Jobs"])
def save_job(request: SaveJobRequest) -> dict:
    """Create or update a job record (durable snapshot)."""
    try:
        job_id = db.upsert_job(request)
    except Exception as e:
        log.error("save_job_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Database write failed: {e}"
        ) from e
    return {"job_id": job_id}


@app.get("/jobs", tags=["Jobs"])
def list_jobs(
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, count = db.list_jobs(status=status, limit=limit, offset=offset)
    return {
        "items": [item.model_dump() for item in items],
        "count": count,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@app.get("/stats", response_model=StatsResponse, tags=["Stats"])
def get_stats(range: str = Query(default="7d", pattern="^(24h|7d|30d)$")):
    return db.get_stats(range)
