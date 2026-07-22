import json
from unittest.mock import patch

import fakeredis.aioredis
import httpx
import pytest
from k8s_llm_shared import new_id

COLLECTOR_URL = "http://collector:8002"
PROCESSOR_URL = "http://processor:8003"
LLM_URL = "http://llm:8004"
REPORTS_URL = "http://reports:8005"

INCIDENT_ID = new_id()

REPORT_JSON = {
    "incident_id": INCIDENT_ID,
    "incident_summary": "Pod demo-app failed due to missing config.",
    "likely_root_cause": "DATABASE_URL environment variable is not set.",
    "affected_component": "demo-app",
    "failure_category": "config",
    "severity": "critical",
    "confidence": 0.9,
    "supporting_evidence": [
        {"source": "pod_log", "pod": "demo-app-abc", "evidence": "FATAL: missing DATABASE_URL"}
    ],
    "suggested_fix": "Set DATABASE_URL in the deployment.",
    "recommended_commands": ["kubectl describe pod -n demo demo-app-abc"],
    "human_verification_steps": ["Check env vars."],
    "created_at": "2026-07-21T10:05:33Z",
}

RAW_EVIDENCE_JSON = {
    "namespace": "demo",
    "pod_name": "demo-app-abc",
    "current_logs": "ERROR Missing DATABASE_URL",
    "previous_logs": "",
    "pod_status": "CrashLoopBackOff",
    "k8s_events": "Warning BackOff",
    "restart_count": 3,
    "container_states": [],
}

PACKAGE_JSON = {
    "namespace": "demo",
    "pod_name": "demo-app-abc",
    "current_logs": "ERROR Missing DATABASE_URL",
    "previous_logs": "",
    "pod_status_summary": "CrashLoopBackOff",
    "k8s_events_filtered": "Warning BackOff",
    "restart_count": 3,
}


def make_handler(*, fail_stage: str | None = None):
    """Build an httpx.MockTransport handler emulating the four downstreams.

    fail_stage: one of "collector", "processor", "llm", "reports" to make
    that downstream return a 500.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path

        if host == "collector" and path == "/collect":
            if fail_stage == "collector":
                return httpx.Response(500, json={"detail": "kubectl boom"})
            return httpx.Response(200, json=RAW_EVIDENCE_JSON)

        if host == "processor" and path == "/process":
            if fail_stage == "processor":
                return httpx.Response(500, json={"detail": "process boom"})
            return httpx.Response(200, json=PACKAGE_JSON)

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

        if host == "llm" and path == "/analyse":
            if fail_stage == "llm":
                return httpx.Response(500, json={"detail": "llm boom"})
            return httpx.Response(200, json=REPORT_JSON)

        if host == "reports" and path == "/reports":
            if fail_stage == "reports":
                return httpx.Response(500, json={"detail": "db boom"})
            return httpx.Response(201, json={"incident_id": INCIDENT_ID})

        if host == "reports" and path == "/jobs":
            return httpx.Response(201, json={"job_id": "archived"})

        return httpx.Response(404, json={"detail": f"no route {host}{path}"})

    return handler


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_http():
    transport = httpx.MockTransport(make_handler())
    return httpx.AsyncClient(transport=transport)


@pytest.fixture
def mock_http_factory():
    def _make(**kwargs):
        transport = httpx.MockTransport(make_handler(**kwargs))
        return httpx.AsyncClient(transport=transport)

    return _make


@pytest.fixture
def api_client(fake_redis, mock_http):
    """TestClient with app.state wired to fakes (lifespan not run)."""
    from app.main import app
    from fastapi.testclient import TestClient

    app.state.redis = fake_redis
    app.state.http = mock_http
    with patch("app.main.REPORTS_URL", REPORTS_URL):
        yield TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def pipeline(fake_redis, mock_http):
    from app.pipeline import Pipeline
    from app.store import JobStore

    return Pipeline(
        store=JobStore(fake_redis),
        http=mock_http,
        collector_url=COLLECTOR_URL,
        processor_url=PROCESSOR_URL,
        llm_url=LLM_URL,
        reports_url=REPORTS_URL,
        timeout_seconds=30,
    )


def read_sse_events(body: str) -> list[dict]:
    """Parse an SSE body into (event, data) tuples."""
    events = []
    event_type = None
    for line in body.splitlines():
        if line.startswith("event: "):
            event_type = line[len("event: "):]
        elif line.startswith("data: ") and event_type:
            events.append((event_type, json.loads(line[len("data: "):])))
            event_type = None
    return events


async def recv_pubsub(pubsub, attempts: int = 20):
    """Poll a (fake) pubsub until a real message arrives.

    fakeredis delivers published messages only after the event loop
    yields, so a single get_message call often returns None. Real Redis
    does not have this quirk — this helper is test-only.
    """
    import asyncio

    for _ in range(attempts):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if msg is not None:
            return msg
        await asyncio.sleep(0.01)
    return None


async def drain_pubsub(pubsub) -> list[dict]:
    """Collect all currently pending published messages."""
    import asyncio

    messages = []
    # Give fakeredis a chance to deliver everything
    for _ in range(50):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.02)
        if msg is not None:
            messages.append(msg)
        else:
            await asyncio.sleep(0.01)
    return messages
