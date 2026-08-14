"""Cross-service integration test — the full microservices pipeline in-process.

Composes the real FastAPI apps of collector-svc, processor-svc, llm-svc
(mock provider), reports-svc (tmp SQLite) and orchestrator-svc
(fakeredis), wires them together with a hostname-routing httpx transport,
and drives a complete analysis job end-to-end:

    POST /jobs → queued → collecting → processing → llm_call → persisting
    → done → report retrievable from reports-svc

Everything runs in a single event loop (httpx ASGITransport everywhere),
so the orchestrator's background pipeline task progresses deterministically.
No live cluster, no Docker, no real Redis required.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis.aioredis
import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_service_app(service: str, env: dict | None = None):
    """Import services/<service> FastAPI app with module isolation.

    Every service uses the package name ``app`` — load them one at a time,
    keep the FastAPI instance, then restore sys.modules so the next
    service can be loaded. Already-imported apps keep working because
    their route handlers hold references to their own module objects.
    """
    service_dir = str(REPO_ROOT / "services" / service)
    with patch.dict(os.environ, env or {}):
        saved = {
            k: v for k, v in sys.modules.items()
            if k == "app" or k.startswith("app.")
        }
        for k in list(sys.modules):
            if k == "app" or k.startswith("app."):
                del sys.modules[k]
        sys.path.insert(0, service_dir)
        try:
            import app.main as service_main

            fastapi_app = service_main.app
        finally:
            sys.path.remove(service_dir)
            for k in list(sys.modules):
                if k == "app" or k.startswith("app."):
                    del sys.modules[k]
            sys.modules.update(saved)
    return fastapi_app


class RouterTransport(httpx.AsyncBaseTransport):
    """Route httpx requests to in-process service apps by hostname."""

    def __init__(self, routes: dict[str, httpx.ASGITransport]):
        self._routes = routes

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        transport = self._routes.get(request.url.host)
        if transport is None:
            return httpx.Response(404, json={"detail": f"no route {request.url.host}"})
        return await transport.handle_async_request(request)


def _kubectl_mock(stdout_map: list[str]):
    """Build subprocess.run return values for the collector's 7 calls."""
    def make(stdout):
        m = MagicMock()
        m.stdout = stdout
        m.stderr = ""
        m.returncode = 0
        return m

    return [make(s) for s in stdout_map]


# ── Scenario 01: missing-env ──────────────────────────────────────────
CONFIG_SCENARIO_OUTPUTS = [
    "demo-app-abc",                                   # _pod_exists
    "ERROR missing DATABASE_URL environment variable",  # current logs
    "ERROR missing DATABASE_URL environment variable",  # previous logs
    "Last State: Terminated\nReason: CrashLoopBackOff",  # describe
    "Warning BackOff Restarting container",           # events
    "3",                                              # restart count
    "[]",                                             # container states
]

# ── Scenario 02: db-unavailable ──────────────────────────────────────
DB_UNAVAILABLE_OUTPUTS = [
    "demo-app-abc",
    "ERROR: Application error: RuntimeError: Database connection failed: connection refused",
    "",
    "Name:         demo-app-abc\nState:  Running\nReady: False\n"
    "Warning  Unhealthy  1m  Readiness probe failed: HTTP probe failed 500",
    "Warning Unhealthy: Readiness probe failed: HTTP probe failed with statuscode: 500",
    "0",
    "[]",
]

# ── Scenario 03: crashloop ───────────────────────────────────────────
CRASHLOOP_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Waiting\n"
    "Reason:       CrashLoopBackOff\n"
    "Last State:   Terminated\n"
    "Reason:       ContainerCannotRun\n"
    "Message:      executable file not found in $PATH: /bin/nonexistent\n"
    "Exit Code:    127\nReady: False\nRestart Count:  8",
    "Warning BackOff: Back-off restarting failed container\n"
    "Warning Failed: Error: container has failed to start",
    "8",
    "[]",
]

# ── Scenario 04: imagepull ───────────────────────────────────────────
IMAGEPULL_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Waiting\n"
    "Reason:       ImagePullBackOff\nReady: False\n"
    "Failed to pull image demo-app:nonexistent-tag: manifest not found",
    "Warning Failed: Error: ImagePullBackOff\n"
    "Warning Failed: Failed to pull image demo-app:nonexistent-tag\n"
    "Warning BackOff: Back-off pulling image demo-app:nonexistent-tag",
    "0",
    "[]",
]

# ── Scenario 05: oom ─────────────────────────────────────────────────
OOM_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Running\n"
    "Last State:   Terminated\n"
    "Reason:       OOMKilled\nExit Code:    137\nReady: True\nRestart Count:  3",
    "Warning Killing: Container demo-app was killed due to OOMKilled\n"
    "Warning BackOff: Back-off restarting failed container",
    "3",
    "[]",
]

# ── Scenario 06: readiness ───────────────────────────────────────────
READINESS_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Running\nReady: False\n"
    "Warning  Unhealthy  5m  Readiness probe failed: HTTP probe failed with statuscode: 404",
    "Warning Unhealthy: Readiness probe failed: HTTP probe failed with statuscode: 404\n"
    "Warning Unhealthy: Readiness probe failed: HTTP probe failed with statuscode: 404",
    "0",
    "[]",
]

# ── Scenario 07: liveness ────────────────────────────────────────────
LIVENESS_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Running\n"
    "Last State:   Terminated\nReason: Error\nExit Code: 137\nReady: True\nRestart Count: 4\n"
    "Warning  Unhealthy  2m  Liveness probe failed: HTTP probe failed with statuscode: 504\n"
    "Warning  Killing   2m  Container demo-app failed liveness probe",
    "Warning Unhealthy: Liveness probe failed: HTTP probe failed with statuscode: 504\n"
    "Warning Killing: Container demo-app failed liveness probe",
    "4",
    "[]",
]

# ── Scenario 08: bad-configmap ───────────────────────────────────────
BAD_CONFIGMAP_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Running\nReady: True\n"
    "Environment Variables from ConfigMap:\n"
    "  APP_ENV=development\n  LOG_LEVEL=INVALID",
    "",
    "0",
    "[]",
]

# ── Scenario 09: app-exception ───────────────────────────────────────
APP_EXCEPTION_OUTPUTS = [
    "demo-app-abc",
    "",
    "FATAL: STARTUP_FAULT=crash -- raising exception on startup\n"
    "RuntimeError: Deliberate startup crash for scenario testing\n"
    "Traceback (most recent call last):\n"
    "  File app/main.py, line 19, in lifespan\n"
    "    raise RuntimeError('Deliberate startup crash')",
    "Name:         demo-app-abc\nState:  Waiting\n"
    "Reason:       CrashLoopBackOff\n"
    "Last State:   Terminated\nReason: Error\nExit Code: 1\nReady: False\nRestart Count: 6",
    "Warning BackOff: Back-off restarting failed container",
    "6",
    "[]",
]

# ── Scenario 10: wrong-port ──────────────────────────────────────────
WRONG_PORT_OUTPUTS = [
    "demo-app-abc",
    "",
    "",
    "Name:         demo-app-abc\nState:  Running\nReady: True\n"
    "Port:         8000/TCP",
    "",
    "0",
    "[]",
]

EMPTY_SCENARIO_OUTPUTS = ["demo-app-abc", "", "", "", "", "0", "[]"]

ALL_SCENARIOS = [
    ("01-missing-env", CONFIG_SCENARIO_OUTPUTS, "config"),
    ("02-db-unavailable", DB_UNAVAILABLE_OUTPUTS, "dependency"),
    ("03-crashloop", CRASHLOOP_OUTPUTS, "crash"),
    ("04-imagepull", IMAGEPULL_OUTPUTS, "image"),
    ("05-oom", OOM_OUTPUTS, "resource"),
    ("06-readiness", READINESS_OUTPUTS, "probe"),
    ("07-liveness", LIVENESS_OUTPUTS, "probe"),
    ("08-bad-configmap", BAD_CONFIGMAP_OUTPUTS, "unknown"),
    ("09-app-exception", APP_EXCEPTION_OUTPUTS, "crash"),
    ("10-wrong-port", WRONG_PORT_OUTPUTS, "unknown"),
]


@pytest.fixture
def stack(tmp_path):
    """Assemble the in-process microservices stack."""
    collector_app = load_service_app("collector")
    processor_app = load_service_app("processor")
    llm_app = load_service_app("llm", env={"LLM_PROVIDER": "mock"})
    reports_app = load_service_app(
        "reports", env={"DATABASE_PATH": str(tmp_path / "reports.db")}
    )
    orchestrator_app = load_service_app(
        "orchestrator",
        env={
            "COLLECTOR_URL": "http://collector:8002",
            "PROCESSOR_URL": "http://processor:8003",
            "LLM_URL": "http://llm:8004",
            "REPORTS_URL": "http://reports:8005",
        },
    )

    router = RouterTransport(
        {
            "collector": httpx.ASGITransport(collector_app),
            "processor": httpx.ASGITransport(processor_app),
            "llm": httpx.ASGITransport(llm_app),
            "reports": httpx.ASGITransport(reports_app),
        }
    )
    orchestrator_app.state.redis = fakeredis.aioredis.FakeRedis(
        decode_responses=True
    )
    orchestrator_app.state.http = httpx.AsyncClient(transport=router)

    return {
        "orchestrator_app": orchestrator_app,
        "reports_app": reports_app,
    }


async def _run_job(stack, namespace: str, pod_name: str) -> dict:
    """Create a job and poll until it reaches a terminal state."""
    orch_transport = httpx.ASGITransport(stack["orchestrator_app"])
    async with httpx.AsyncClient(
        transport=orch_transport, base_url="http://orchestrator"
    ) as client:
        resp = await client.post(
            "/jobs", json={"namespace": namespace, "pod_name": pod_name}
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        assert len(job_id) == 36  # UUID format

        job = None
        for _ in range(150):
            await asyncio.sleep(0.1)
            resp = await client.get(f"/jobs/{job_id}")
            assert resp.status_code == 200
            job = resp.json()
            if job["status"] in ("done", "failed"):
                break
    assert job is not None
    return job


class TestFullPipeline:
    async def _run_and_verify(self, stack, kubectl_outputs, expected_category):
        """Run a job with the given kubectl mock outputs and verify the report."""
        with patch(
            "subprocess.run",
            side_effect=_kubectl_mock(kubectl_outputs),
        ):
            job = await _run_job(stack, "demo", "demo-app")

        assert job["status"] == "done", f"job failed: {job.get('error')}"
        assert job["incident_id"]
        assert job["latency_ms"] is not None and job["latency_ms"] >= 0

        reports_transport = httpx.ASGITransport(stack["reports_app"])
        async with httpx.AsyncClient(
            transport=reports_transport, base_url="http://reports"
        ) as reports:
            resp = await reports.get(f"/reports/{job['incident_id']}")
            assert resp.status_code == 200
            report = resp.json()
            assert report["failure_category"] == expected_category, (
                f"Expected {expected_category}, got {report['failure_category']}"
            )
            assert len(report["supporting_evidence"]) >= 1
            assert report["created_at"]

            resp = await reports.get(f"/jobs?status=done&limit=50")
            archived = resp.json()
            archived_job = next(
                (j for j in archived["items"] if j["job_id"] == job["job_id"]),
                None,
            )
            assert archived_job is not None, "Job not archived in reports-svc"
            assert archived_job["incident_id"] == job["incident_id"]

        return job, report

    # ── Original tests (kept for backward compatibility) ──────────────

    async def test_config_scenario_end_to_end(self, stack):
        job, report = await self._run_and_verify(
            stack, CONFIG_SCENARIO_OUTPUTS, "config"
        )
        assert "DATABASE_URL" in report["likely_root_cause"]

    async def test_unknown_scenario_end_to_end(self, stack):
        """Empty evidence still completes — mock LLM returns 'unknown'."""
        with patch(
            "subprocess.run", side_effect=_kubectl_mock(EMPTY_SCENARIO_OUTPUTS)
        ):
            job = await _run_job(stack, "demo", "demo-app")

        assert job["status"] == "done", f"job failed: {job.get('error')}"

        reports_transport = httpx.ASGITransport(stack["reports_app"])
        async with httpx.AsyncClient(
            transport=reports_transport, base_url="http://reports"
        ) as reports:
            resp = await reports.get(f"/reports/{job['incident_id']}")
            assert resp.json()["failure_category"] == "unknown"

    # ── All 10 scenario tests ────────────────────────────────────────

    @pytest.mark.parametrize("scenario_id,kubectl_outputs,expected_category", ALL_SCENARIOS)
    async def test_scenario_end_to_end(self, stack, scenario_id, kubectl_outputs, expected_category):
        """End-to-end pipeline test for each fault scenario."""
        await self._run_and_verify(stack, kubectl_outputs, expected_category)

    async def test_health_endpoints_all_up(self, stack):
        for app_name, service in (
            ("orchestrator_app", "orchestrator-svc"),
            ("reports_app", "reports-svc"),
        ):
            transport = httpx.ASGITransport(stack[app_name])
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["service"] == service


class TestLLMConfigRuntime:
    """The Settings page flow: writing a key to the config file makes a
    provider available and the active selection resolves at analysis time."""

    @pytest.fixture
    def llm_env(self, tmp_path):
        config_path = str(tmp_path / "llm-config.json")
        load_service_app(
            "llm",
            env={"LLM_PROVIDER": "mock", "LLM_CONFIG_PATH": config_path},
        )
        # The store reads LLM_CONFIG_PATH at request time, so re-patch it
        # around every request (the import-time patch has already ended).
        return config_path

    def _client(self, config_path):
        app = load_service_app("llm")
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://llm"
        )

    async def test_config_roundtrip_never_echoes_key(self, llm_env):
        with patch.dict(os.environ, {"LLM_CONFIG_PATH": llm_env}):
            async with self._client(llm_env) as client:
                resp = await client.post(
                    "/config",
                    json={"provider": "openai", "api_key": "sk-integration-secret"},
                )
                assert resp.status_code == 200
                status = resp.json()
                assert status["provider"] == "openai"
                assert status["source"] == "file"
                openai_item = next(
                    p for p in status["providers"] if p["id"] == "openai"
                )
                assert openai_item["available"] is True
                assert "sk-integration-secret" not in resp.text

                resp = await client.get("/config")
                assert resp.status_code == 200
                assert "sk-integration-secret" not in resp.text

                resp = await client.get("/providers")
                items = {p["id"]: p for p in resp.json()["items"]}
                assert items["openai"]["available"] is True

    async def test_cleared_key_makes_provider_unavailable(self, llm_env):
        with patch.dict(os.environ, {"LLM_CONFIG_PATH": llm_env}):
            async with self._client(llm_env) as client:
                await client.post(
                    "/config",
                    json={"provider": "deepseek", "api_key": "dk-secret"},
                )
                resp = await client.post(
                    "/config",
                    json={"provider": "deepseek", "clear_key": True},
                )
                deepseek_item = next(
                    p for p in resp.json()["providers"] if p["id"] == "deepseek"
                )
                assert deepseek_item["available"] is False
