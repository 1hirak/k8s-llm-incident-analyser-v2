"""gateway-svc — public API entry point.

Implements contracts/api/gateway.yaml. Proxies frontend requests to the
appropriate internal service (orchestrator, reports-svc, scenario-svc),
adds CORS, rate limiting, and RFC 7807 error translation. The frontend
never talks to internal services directly.
"""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.proxy import proxy_request, proxy_sse
from app.rate_limit import RateLimitMiddleware

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8001")
REPORTS_URL = os.environ.get("REPORTS_URL", "http://localhost:8005")
SCENARIO_URL = os.environ.get("SCENARIO_URL", "http://localhost:8006")
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8004")
COLLECTOR_URL = os.environ.get("COLLECTOR_URL", "http://localhost:8002")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()


app = FastAPI(
    title="gateway-svc",
    description="Public API gateway for the K8s LLM Incident Analyser",
    version="0.1.0",
    lifespan=lifespan,
)
add_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, requests_per_minute=RATE_LIMIT_PER_MINUTE)


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


@app.get("/health", tags=["Health"])
async def health(request: Request) -> dict:
    """Gateway health; includes LLM provider when llm-svc is reachable."""
    provider = None
    cluster = None
    try:
        resp = await _http(request).get(f"{LLM_URL}/health", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            provider = data.get("provider")
    except httpx.HTTPError:
        pass
    try:
        resp = await _http(request).get(f"{COLLECTOR_URL}/health", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            cluster = data.get("cluster")
    except httpx.HTTPError:
        pass
    return health_payload("gateway-svc", provider=provider, cluster=cluster)


# ---------------------------------------------------------------------------
# Jobs (orchestrator-svc)
# ---------------------------------------------------------------------------


@app.post("/api/jobs", tags=["Jobs"])
async def create_job(request: Request) -> Response:
    return await proxy_request(request, _http(request), ORCHESTRATOR_URL, "/jobs")


@app.get("/api/jobs", tags=["Jobs"])
async def list_jobs(request: Request) -> Response:
    return await proxy_request(request, _http(request), ORCHESTRATOR_URL, "/jobs")


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str, request: Request) -> Response:
    return await proxy_request(
        request, _http(request), ORCHESTRATOR_URL, f"/jobs/{job_id}"
    )


@app.get("/api/jobs/{job_id}/stream", tags=["Jobs"])
async def stream_job(job_id: str, request: Request) -> Response:
    factory = getattr(request.app.state, "sse_client_factory", None)
    return await proxy_sse(
        request,
        _http(request),
        ORCHESTRATOR_URL,
        f"/jobs/{job_id}/stream",
        client_factory=factory,
    )


# ---------------------------------------------------------------------------
# Reports + Stats (reports-svc)
# ---------------------------------------------------------------------------


@app.get("/api/reports", tags=["Reports"])
async def list_reports(request: Request) -> Response:
    return await proxy_request(request, _http(request), REPORTS_URL, "/reports")


@app.get("/api/reports/{incident_id}", tags=["Reports"])
async def get_report(incident_id: str, request: Request) -> Response:
    return await proxy_request(
        request, _http(request), REPORTS_URL, f"/reports/{incident_id}"
    )


@app.get("/api/stats", tags=["Stats"])
async def get_stats(request: Request) -> Response:
    return await proxy_request(request, _http(request), REPORTS_URL, "/stats")


# ---------------------------------------------------------------------------
# Scenarios (scenario-svc)
# ---------------------------------------------------------------------------


@app.get("/api/scenarios", tags=["Scenarios"])
async def list_scenarios(request: Request) -> Response:
    return await proxy_request(request, _http(request), SCENARIO_URL, "/scenarios")


@app.post("/api/scenarios/reset", tags=["Scenarios"])
async def reset_scenarios(request: Request) -> Response:
    return await proxy_request(
        request, _http(request), SCENARIO_URL, "/scenarios/reset"
    )


@app.post("/api/scenarios/{scenario_id}/apply", tags=["Scenarios"])
async def apply_scenario(scenario_id: str, request: Request) -> Response:
    return await proxy_request(
        request, _http(request), SCENARIO_URL, f"/scenarios/{scenario_id}/apply"
    )
