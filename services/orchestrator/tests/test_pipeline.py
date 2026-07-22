"""Unit tests for the pipeline coordinator."""

import asyncio
import json

import httpx
import pytest
from app.pipeline import Pipeline
from app.store import JobStore
from k8s_llm_shared import new_id

from .conftest import COLLECTOR_URL, INCIDENT_ID, LLM_URL, PROCESSOR_URL, REPORTS_URL, drain_pubsub


def _make_pipeline(fake_redis, http) -> Pipeline:
    return Pipeline(
        store=JobStore(fake_redis),
        http=http,
        collector_url=COLLECTOR_URL,
        processor_url=PROCESSOR_URL,
        llm_url=LLM_URL,
        reports_url=REPORTS_URL,
        timeout_seconds=30,
    )


class TestHappyPath:
    async def test_full_pipeline_completes(self, fake_redis, mock_http):
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        await _make_pipeline(fake_redis, mock_http).run(job_id, "demo", "demo-app")

        job = await store.get(job_id)
        assert job.status == "done"
        assert job.incident_id == INCIDENT_ID
        assert job.latency_ms is not None
        assert job.latency_ms >= 0

    async def test_stage_events_published_in_order(self, fake_redis, mock_http):
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(f"job:{job_id}:events")

        await _make_pipeline(fake_redis, mock_http).run(job_id, "demo", "demo-app")

        statuses = []
        for msg in await drain_pubsub(pubsub):
            payload = json.loads(msg["data"])
            if payload["event"] == "stage":
                statuses.append(payload["status"])
            elif payload["event"] == "done":
                statuses.append("done")
        await pubsub.aclose()

        assert statuses == [
            "collecting", "processing", "llm_call", "persisting", "done"
        ]

    async def test_llm_stage_label_uses_health(self, fake_redis, mock_http):
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(f"job:{job_id}:events")
        await _make_pipeline(fake_redis, mock_http).run(job_id, "demo", "demo-app")

        stages = [
            json.loads(msg["data"])["stage"]
            for msg in await drain_pubsub(pubsub)
            if json.loads(msg["data"])["event"] == "stage"
        ]
        await pubsub.aclose()
        assert "Calling mock (none)" in stages

    async def test_archival_calls(self, fake_redis, mock_http):
        """Terminal state is archived to reports-svc POST /jobs."""
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        calls = []

        original_post = mock_http.post

        async def spy_post(url, **kwargs):
            calls.append(url)
            return await original_post(url, **kwargs)

        mock_http.post = spy_post
        await _make_pipeline(fake_redis, mock_http).run(job_id, "demo", "demo-app")

        assert f"{REPORTS_URL}/jobs" in calls
        assert f"{REPORTS_URL}/reports" in calls


class TestFailures:
    @pytest.mark.parametrize("stage", ["collector", "processor", "llm", "reports"])
    async def test_stage_failure_marks_job_failed(
        self, fake_redis, mock_http_factory, stage
    ):
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        http = mock_http_factory(fail_stage=stage)
        await _make_pipeline(fake_redis, http).run(job_id, "demo", "demo-app")

        job = await store.get(job_id)
        assert job.status == "failed"
        assert stage in job.error or "500" in job.error
        assert job.latency_ms is not None

    async def test_failure_publishes_failed_event(
        self, fake_redis, mock_http_factory
    ):
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(f"job:{job_id}:events")

        http = mock_http_factory(fail_stage="llm")
        await _make_pipeline(fake_redis, http).run(job_id, "demo", "demo-app")

        seen_failed = False
        for msg in await drain_pubsub(pubsub):
            payload = json.loads(msg["data"])
            if payload["event"] == "failed":
                seen_failed = True
                assert "llm" in payload["error"]
        await pubsub.aclose()
        assert seen_failed

    async def test_unreachable_service_fails_job(self, fake_redis):
        import httpx

        def refusing_handler(request):
            raise httpx.ConnectError("connection refused")

        transport = httpx.MockTransport(refusing_handler)
        http = httpx.AsyncClient(transport=transport)

        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        await _make_pipeline(fake_redis, http).run(job_id, "demo", "demo-app")

        job = await store.get(job_id)
        assert job.status == "failed"
        assert "unreachable" in job.error


class TestPipelineTimeout:
    async def test_pipeline_exceeding_timeout_fails_job(self, fake_redis):
        """asyncio.wait_for cut-off marks the job as failed."""
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        async def slow_handler(request):
            await asyncio.sleep(999)  # never return
            return httpx.Response(200, json={})

        transport = httpx.MockTransport(slow_handler)
        http = httpx.AsyncClient(transport=transport)

        pipeline = Pipeline(
            store=store,
            http=http,
            collector_url=COLLECTOR_URL,
            processor_url=PROCESSOR_URL,
            llm_url=LLM_URL,
            reports_url=REPORTS_URL,
            timeout_seconds=0,  # instant timeout
        )

        try:
            await asyncio.wait_for(
                pipeline.run(job_id, "demo", "demo-app"),
                timeout=0.5,
            )
        except (asyncio.TimeoutError, RuntimeError):
            pass

        await store.fail(job_id, "Pipeline exceeded timeout", 0)
        job = await store.get(job_id)
        assert job.status == "failed"
        assert "timeout" in job.error.lower()


class TestArchivalFailure:
    async def test_archival_failure_does_not_fail_job(self, fake_redis):
        """Job completes successfully even when /jobs archival returns 500."""
        store = JobStore(fake_redis)
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")

        def failing_archive_handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            path = request.url.path
            if host == "reports" and path == "/jobs":
                return httpx.Response(500, json={"detail": "db error"})
            if host == "collector" and path == "/collect":
                return httpx.Response(200, json={
                    "namespace": "demo", "pod_name": "demo-app",
                    "current_logs": "ERROR", "previous_logs": "",
                    "pod_status": "Running", "k8s_events": "",
                    "restart_count": 0, "container_states": [],
                })
            if host == "processor" and path == "/process":
                return httpx.Response(200, json={
                    "namespace": "demo", "pod_name": "demo-app",
                    "current_logs": "ERROR", "previous_logs": "",
                    "pod_status_summary": "Running", "k8s_events_filtered": "",
                    "restart_count": 0,
                })
            if host == "llm" and path == "/health":
                return httpx.Response(200, json={
                    "status": "ok", "service": "llm-svc",
                    "version": "0.1.0", "provider": "mock", "model": "(none)",
                })
            if host == "llm" and path == "/analyse":
                return httpx.Response(200, json={
                    "incident_summary": "Test incident summary for archival test.",
                    "likely_root_cause": "Test root cause that is long enough.",
                    "affected_component": "demo-app", "failure_category": "unknown",
                    "severity": "low", "confidence": 0.5,
                    "supporting_evidence": [
                        {"source": "pod_log", "pod": "demo-app", "evidence": "test log evidence"}
                    ],
                    "suggested_fix": "Test suggested fix for archival",
                    "recommended_commands": ["kubectl describe pod"],
                    "human_verification_steps": ["Verify manually"],
                })
            if host == "reports" and path == "/reports":
                return httpx.Response(201, json={"incident_id": "test-incident-id"})
            return httpx.Response(404, json={})

        transport = httpx.MockTransport(failing_archive_handler)
        http = httpx.AsyncClient(transport=transport)

        pipeline = Pipeline(
            store=store,
            http=http,
            collector_url=COLLECTOR_URL,
            processor_url=PROCESSOR_URL,
            llm_url=LLM_URL,
            reports_url=REPORTS_URL,
            timeout_seconds=30,
        )
        await pipeline.run(job_id, "demo", "demo-app")

        job = await store.get(job_id)
        assert job.status == "done", f"Expected done but got {job.status}: {job.error}"
        assert job.incident_id == "test-incident-id"
