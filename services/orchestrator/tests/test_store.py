"""Unit tests for the Redis job store (contracts/database/redis_schema.md)."""

import json

import pytest
from app.store import JOB_QUEUE_KEY, JobStore
from k8s_llm_shared import IncidentReport, new_id

from .conftest import recv_pubsub


@pytest.fixture
def store(fake_redis):
    return JobStore(fake_redis)


def _report() -> IncidentReport:
    return IncidentReport(
        incident_summary="Pod failed due to missing config.",
        likely_root_cause="DATABASE_URL environment variable is not set.",
        affected_component="demo-app",
        failure_category="config",
        severity="critical",
        confidence=0.9,
        supporting_evidence=[
            {"source": "pod_log", "pod": "p", "evidence": "FATAL: missing DATABASE_URL"}
        ],
        suggested_fix="Set DATABASE_URL.",
        recommended_commands=["kubectl describe pod p"],
        human_verification_steps=["Check env vars."],
    )


class TestCreate:
    async def test_create_sets_hash_and_ttl(self, store, fake_redis):
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        data = await fake_redis.hgetall(f"job:{job_id}")
        assert data["status"] == "queued"
        assert data["namespace"] == "demo"
        ttl = await fake_redis.ttl(f"job:{job_id}")
        assert 0 < ttl <= 86400

    async def test_create_pushes_to_queue(self, store, fake_redis):
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        queued = await fake_redis.lrange(JOB_QUEUE_KEY, 0, -1)
        assert job_id in queued

    async def test_clear_queue_removes_all_pending_entries(self, store, fake_redis):
        await store.create(new_id(), "demo", "one")
        await store.create(new_id(), "demo", "two")

        assert await store.clear_queue() == 2
        assert await fake_redis.llen(JOB_QUEUE_KEY) == 0


class TestTransitions:
    async def test_transition_updates_state(self, store):
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        await store.transition(job_id, "collecting", "Collecting evidence")
        job = await store.get(job_id)
        assert job.status == "collecting"
        assert job.stage == "Collecting evidence"

    async def test_transition_publishes_event(self, store, fake_redis):
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(f"job:{job_id}:events")
        await store.transition(job_id, "collecting", "Collecting evidence")
        msg = await recv_pubsub(pubsub)
        assert msg is not None
        payload = json.loads(msg["data"])
        assert payload["event"] == "stage"
        assert payload["status"] == "collecting"
        assert payload["stage"] == "Collecting evidence"
        await pubsub.aclose()

    async def test_complete_sets_terminal_fields(self, store):
        job_id = new_id()
        report = _report()
        await store.create(job_id, "demo", "demo-app")
        await store.complete(job_id, report.incident_id, 6800, report)
        job = await store.get(job_id)
        assert job.status == "done"
        assert job.incident_id == report.incident_id
        assert job.latency_ms == 6800

    async def test_fail_sets_error(self, store):
        job_id = new_id()
        await store.create(job_id, "demo", "demo-app")
        await store.fail(job_id, "kubectl timeout", 1200)
        job = await store.get(job_id)
        assert job.status == "failed"
        assert job.error == "kubectl timeout"
        assert job.latency_ms == 1200


class TestReads:
    async def test_get_missing_returns_none(self, store):
        assert await store.get(new_id()) is None

    async def test_list_pagination_and_order(self, store):
        ids = [new_id() for _ in range(5)]
        for job_id in ids:
            await store.create(job_id, "demo", "demo-app")
        items, count = await store.list(limit=2, offset=0)
        assert count == 5
        assert len(items) == 2
        items, count = await store.list(limit=2, offset=4)
        assert len(items) == 1

    async def test_list_filter_by_status(self, store):
        done_id, failed_id = new_id(), new_id()
        await store.create(done_id, "demo", "a")
        await store.create(failed_id, "demo", "b")
        await store.complete(done_id, new_id(), 100, _report())
        await store.fail(failed_id, "boom", 50)
        items, count = await store.list(status="failed")
        assert count == 1
        assert items[0].job_id == failed_id

    async def test_list_ignores_queue_key(self, store, fake_redis):
        await store.create(new_id(), "demo", "demo-app")
        items, count = await store.list()
        # job:queue must not appear as a job
        assert all(j.namespace == "demo" for j in items)
        assert count == len(items)
