"""API-level tests for orchestrator-svc (contracts/api/orchestrator.yaml)."""

import asyncio

import httpx
from app.store import JobStore
from k8s_llm_shared import new_id

from .conftest import read_sse_events


class TestHealth:
    def test_health_shape(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator-svc"


class TestCreateJob:
    def test_returns_202_with_job_id(self, api_client):
        resp = api_client.post(
            "/jobs", json={"namespace": "demo", "pod_name": "demo-app"}
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        # UUID format
        assert len(data["job_id"]) == 36

    def test_missing_pod_name_returns_400(self, api_client):
        resp = api_client.post("/jobs", json={"namespace": "demo"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == 400
        assert body["title"] == "Invalid request"


class TestGetJob:
    def test_get_existing_job(self, api_client):
        resp = api_client.post(
            "/jobs", json={"namespace": "demo", "pod_name": "demo-app"}
        )
        job_id = resp.json()["job_id"]

        resp = api_client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["namespace"] == "demo"
        assert data["pod_name"] == "demo-app"
        assert data["created_at"]

    def test_get_missing_returns_404_problem(self, api_client):
        resp = api_client.get(f"/jobs/{new_id()}")
        assert resp.status_code == 404
        body = resp.json()
        assert body["status"] == 404


class TestListJobs:
    def test_pagination_envelope(self, api_client):
        for _ in range(3):
            api_client.post(
                "/jobs", json={"namespace": "demo", "pod_name": "demo-app"}
            )
        resp = api_client.get("/jobs?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0


class TestStreamJob:
    def test_stream_terminal_job_replays_done(self, api_client, fake_redis):
        job_id = new_id()
        store = JobStore(fake_redis)

        async def setup():
            await store.create(job_id, "demo", "demo-app")
            from k8s_llm_shared import IncidentReport

            from .conftest import REPORT_JSON

            report = IncidentReport(**REPORT_JSON)
            await store.complete(job_id, report.incident_id, 6800, report)

        asyncio.run(setup())

        with api_client.stream("GET", f"/jobs/{job_id}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers.get("x-accel-buffering") == "no"
            body = "".join(resp.iter_text())

        events = read_sse_events(body)
        assert len(events) == 1
        event_type, payload = events[0]
        assert event_type == "done"
        assert payload["job_id"] == job_id
        assert payload["latency_ms"] == 6800

    def test_stream_missing_job_returns_404(self, api_client):
        resp = api_client.get(f"/jobs/{new_id()}/stream")
        assert resp.status_code == 404


class TestStreamLive:
    """Live SSE fanout: replay current state, then forward pub/sub events."""

    async def test_live_stage_then_done(self, fake_redis):
        from app.main import app

        app.state.redis = fake_redis
        app.state.http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        )

        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        await store.transition(job_id, "collecting", "Collecting evidence")

        transport = httpx.ASGITransport(app=app)
        received: list[str] = []

        async def consume():
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                async with client.stream(
                    "GET", f"/jobs/{job_id}/stream"
                ) as resp:
                    # The server closes the stream after the terminal event,
                    # so reading to completion closes all generators cleanly.
                    async for line in resp.aiter_lines():
                        if line:
                            received.append(line)

        consumer = asyncio.create_task(consume())
        # Let the stream subscribe, then drive the job to completion
        await asyncio.sleep(0.2)
        await store.transition(job_id, "processing", "Filtering logs")
        from k8s_llm_shared import IncidentReport

        from .conftest import REPORT_JSON

        report = IncidentReport(**REPORT_JSON)
        await store.complete(job_id, report.incident_id, 5000, report)

        await asyncio.wait_for(consumer, timeout=5)

        body = "\n".join(received)
        events = read_sse_events(body)
        kinds = [e[0] for e in events]
        # replay (collecting) + live processing + done
        assert kinds[0] == "stage"
        assert "done" in kinds
        statuses = [e[1]["status"] for e in events if e[0] == "stage"]
        assert "collecting" in statuses
        assert "processing" in statuses
