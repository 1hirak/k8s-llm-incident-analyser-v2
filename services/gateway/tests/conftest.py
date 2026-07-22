import os

# Point the gateway at the emulated upstream hosts before app.main is imported
os.environ.update(
    {
        "ORCHESTRATOR_URL": "http://orchestrator:8001",
        "REPORTS_URL": "http://reports:8005",
        "SCENARIO_URL": "http://scenario:8006",
        "LLM_URL": "http://llm:8004",
        "RATE_LIMIT_PER_MINUTE": "60",
    }
)

import httpx
import pytest
from k8s_llm_shared import new_id

JOB_ID = new_id()
INCIDENT_ID = new_id()

JOB_STATE = {
    "job_id": JOB_ID,
    "namespace": "demo",
    "pod_name": "demo-app",
    "status": "queued",
    "stage": None,
    "incident_id": None,
    "latency_ms": None,
    "error": None,
    "created_at": "2026-07-21T10:05:33Z",
    "updated_at": "2026-07-21T10:05:33Z",
}

REPORT = {
    "incident_id": INCIDENT_ID,
    "incident_summary": "Pod demo-app failed to start.",
    "likely_root_cause": "DATABASE_URL environment variable is not set.",
    "affected_component": "demo-app",
    "failure_category": "config",
    "severity": "critical",
    "confidence": 0.9,
    "supporting_evidence": [
        {"source": "pod_log", "pod": "demo-app", "evidence": "FATAL missing"}
    ],
    "suggested_fix": "Set DATABASE_URL.",
    "recommended_commands": ["kubectl describe pod demo-app"],
    "human_verification_steps": ["Check env vars."],
    "created_at": "2026-07-21T10:05:33Z",
}

SSE_BODY = (
    "event: stage\n"
    f'data: {{"event":"stage","job_id":"{JOB_ID}","status":"collecting",'
    '"stage":"Collecting evidence","updated_at":"2026-07-21T10:05:34Z"}\n\n'
    "event: done\n"
    f'data: {{"event":"done","job_id":"{JOB_ID}","status":"done",'
    f'"incident_id":"{INCIDENT_ID}","failure_category":"config",'
    '"severity":"critical","latency_ms":6800}\n\n'
)


def upstream_handler(request: httpx.Request) -> httpx.Response:
    """Emulates orchestrator, reports-svc, scenario-svc and llm-svc."""
    host, path = request.url.host, request.url.path

    # orchestrator
    if host == "orchestrator":
        if path == "/jobs" and request.method == "POST":
            return httpx.Response(
                202, json={"job_id": JOB_ID, "status": "queued"}
            )
        if path == "/jobs" and request.method == "GET":
            return httpx.Response(
                200,
                json={"items": [JOB_STATE], "count": 1, "limit": 20, "offset": 0},
            )
        if path == f"/jobs/{JOB_ID}/stream":
            return httpx.Response(
                200,
                text=SSE_BODY,
                headers={"content-type": "text/event-stream"},
            )
        if path == f"/jobs/{JOB_ID}":
            return httpx.Response(200, json=JOB_STATE)
        if path.startswith("/jobs/"):
            return httpx.Response(
                404,
                json={
                    "type": "https://errors.k8s-llm.io/not-found",
                    "title": "Not found",
                    "status": 404,
                    "detail": "Job not found",
                },
            )

    # reports-svc
    if host == "reports":
        if path == "/reports" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "incident_id": INCIDENT_ID,
                            "namespace": "demo",
                            "pod_name": "demo-app",
                            "failure_category": "config",
                            "severity": "critical",
                            "confidence": 0.9,
                            "incident_summary": "Pod failed.",
                            "created_at": "2026-07-21T10:05:33Z",
                        }
                    ],
                    "count": 1,
                    "limit": 20,
                    "offset": 0,
                },
            )
        if path == f"/reports/{INCIDENT_ID}":
            return httpx.Response(200, json=REPORT)
        if path == "/stats":
            return httpx.Response(
                200,
                json={
                    "total_reports": 1,
                    "reports_24h": 1,
                    "mean_latency_ms": 6800.0,
                    "mean_confidence": 0.9,
                    "category_counts": {"config": 1},
                    "latency_series": [],
                },
            )

    # scenario-svc
    if host == "scenario":
        if path == "/scenarios" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "scenario_id": "05-oom",
                            "name": "OOM Killed",
                            "category": "resource",
                            "description": "Memory limit 32Mi",
                            "severity": "high",
                        }
                    ]
                },
            )
        if path == "/scenarios/05-oom/apply" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "applied": True,
                    "scenario_id": "05-oom",
                    "fault_description": "Memory limit reduced to 32Mi",
                },
            )
        if path == "/scenarios/reset" and request.method == "POST":
            return httpx.Response(200, json={"reset": True})

    # llm-svc
    if host == "llm" and path == "/health":
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "llm-svc",
                "version": "0.1.0",
                "provider": "mock",
                "model": "(none)",
            },
        )

    return httpx.Response(404, json={"detail": f"no route {host}{path}"})


def _reset_rate_limiter(app) -> None:
    """Clear the rate limiter's per-IP counters (test isolation)."""
    from app.rate_limit import RateLimitMiddleware

    if app.middleware_stack is None:
        app.middleware_stack = app.build_middleware_stack()
    mw = app.middleware_stack
    while mw is not None:
        if isinstance(mw, RateLimitMiddleware):
            mw._hits.clear()
            return
        mw = getattr(mw, "app", None)


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    from app.main import app

    _reset_rate_limiter(app)
    yield
    _reset_rate_limiter(app)


@pytest.fixture
def api_client():
    """TestClient with upstreams emulated by httpx.MockTransport."""
    from app.main import app
    from fastapi.testclient import TestClient

    transport = httpx.MockTransport(upstream_handler)
    app.state.http = httpx.AsyncClient(transport=transport)
    app.state.sse_client_factory = lambda: httpx.AsyncClient(
        transport=transport, timeout=None
    )
    return TestClient(app, raise_server_exceptions=False)
