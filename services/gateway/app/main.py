"""gateway-svc — public API entry point.

Implements contracts/api/gateway.yaml. Proxies frontend requests to the
appropriate internal service (orchestrator, reports-svc, scenario-svc),
adds CORS, rate limiting, and RFC 7807 error translation. The frontend
never talks to internal services directly.
"""

import hmac
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.proxy import proxy_request, proxy_sse
from app.rate_limit import RateLimitMiddleware

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8001")
REPORTS_URL = os.environ.get("REPORTS_URL", "http://localhost:8005")
SCENARIO_URL = os.environ.get("SCENARIO_URL", "http://localhost:8006")
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8004")
COLLECTOR_URL = os.environ.get("COLLECTOR_URL", "http://localhost:8002")
REMEDIATION_URL = os.environ.get("REMEDIATION_URL", "http://localhost:8008")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))
GATEWAY_API_TOKEN = os.environ.get("GATEWAY_API_TOKEN", "")
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]


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
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, requests_per_minute=RATE_LIMIT_PER_MINUTE)


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    """Optionally protect every public endpoint with one gateway token.

    Development keeps the token empty for backwards compatibility. Production
    deployments must set GATEWAY_API_TOKEN and pass it as a Bearer token.
    """
    if (
        GATEWAY_API_TOKEN
        and request.url.path != "/health"
        and request.method != "OPTIONS"
    ):
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {GATEWAY_API_TOKEN}"
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={
                    "type": "https://errors.k8s-llm.io/unauthorized",
                    "title": "Authentication required",
                    "status": 401,
                    "detail": "Provide a valid gateway Bearer token.",
                },
                media_type="application/problem+json",
            )
    return await call_next(request)


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


@app.get("/api/targets", tags=["Targets"])
async def list_targets(request: Request) -> Response:
    return await proxy_request(request, _http(request), COLLECTOR_URL, "/targets")


@app.get("/api/cluster/status", tags=["Health"])
async def cluster_status(request: Request) -> Response:
    return await proxy_request(request, _http(request), COLLECTOR_URL, "/status")


# ---------------------------------------------------------------------------
# Jobs (orchestrator-svc)
# ---------------------------------------------------------------------------


@app.post("/api/jobs", tags=["Jobs"])
async def create_job(request: Request) -> Response:
    return await proxy_request(request, _http(request), ORCHESTRATOR_URL, "/jobs")


@app.get("/api/jobs", tags=["Jobs"])
async def list_jobs(request: Request) -> Response:
    return await proxy_request(request, _http(request), ORCHESTRATOR_URL, "/jobs")


@app.post("/api/jobs/queue/clear", tags=["Jobs"])
async def clear_job_queue(request: Request) -> Response:
    return await proxy_request(
        request, _http(request), ORCHESTRATOR_URL, "/jobs/queue/clear"
    )


@app.post("/api/jobs/active/cancel", tags=["Jobs"])
async def cancel_active_jobs(request: Request) -> Response:
    return await proxy_request(
        request, _http(request), ORCHESTRATOR_URL, "/jobs/active/cancel"
    )


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str, request: Request) -> Response:
    return await proxy_request(
        request, _http(request), ORCHESTRATOR_URL, f"/jobs/{job_id}"
    )


@app.post("/api/jobs/{job_id}/cancel", tags=["Jobs"])
async def cancel_job(job_id: str, request: Request) -> Response:
    return await proxy_request(
        request, _http(request), ORCHESTRATOR_URL, f"/jobs/{job_id}/cancel"
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


# ---------------------------------------------------------------------------
# Settings (llm-svc)
# ---------------------------------------------------------------------------


@app.get("/api/settings", tags=["Settings"])
async def get_settings(request: Request) -> Response:
    return await proxy_request(request, _http(request), LLM_URL, "/config")


@app.post("/api/settings", tags=["Settings"])
async def save_settings(request: Request) -> Response:
    return await proxy_request(request, _http(request), LLM_URL, "/config")


@app.get("/api/settings/providers", tags=["Settings"])
async def list_settings_providers(request: Request) -> Response:
    return await proxy_request(request, _http(request), LLM_URL, "/providers")


# ---------------------------------------------------------------------------
# Approved remediation (remediation-svc)
# ---------------------------------------------------------------------------


@app.post("/api/remediations", tags=["Remediation"])
async def create_remediation(request: Request) -> Response:
    return await proxy_request(request, _http(request), REMEDIATION_URL, "/remediations")


@app.get("/api/remediations/{remediation_id}", tags=["Remediation"])
async def get_remediation(remediation_id: str, request: Request) -> Response:
    return await proxy_request(
        request,
        _http(request),
        REMEDIATION_URL,
        f"/remediations/{remediation_id}",
    )


@app.post("/api/remediations/{remediation_id}/approve", tags=["Remediation"])
async def approve_remediation(remediation_id: str, request: Request) -> Response:
    return await proxy_request(
        request,
        _http(request),
        REMEDIATION_URL,
        f"/remediations/{remediation_id}/approve",
    )


@app.post("/api/remediations/{remediation_id}/reject", tags=["Remediation"])
async def reject_remediation(remediation_id: str, request: Request) -> Response:
    return await proxy_request(
        request,
        _http(request),
        REMEDIATION_URL,
        f"/remediations/{remediation_id}/reject",
    )
