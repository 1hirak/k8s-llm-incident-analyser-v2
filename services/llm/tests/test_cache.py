import json

import pytest
from app.cache import AnalysisCache, build_cache_key
from k8s_llm_shared import EvidencePackage, IncidentReport


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def package():
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc",
        current_logs="ERROR Missing DATABASE_URL",
        previous_logs="",
        pod_status_summary="CrashLoopBackOff",
        k8s_events_filtered="Warning BackOff",
        restart_count=3,
    )


@pytest.fixture
def report():
    return IncidentReport(
        incident_summary="Configuration failure",
        likely_root_cause="DATABASE_URL is missing",
        affected_component="demo-app-abc",
        failure_category="config",
        severity="critical",
        confidence=0.9,
        supporting_evidence=[
            {
                "source": "pod_log",
                "pod": "demo-app-abc",
                "evidence": "Missing DATABASE_URL",
            }
        ],
        suggested_fix="Set DATABASE_URL",
        recommended_commands=["kubectl describe pod demo-app-abc"],
        human_verification_steps=["Verify the deployment environment"],
    )


def test_cache_key_changes_when_evidence_changes(package):
    first = build_cache_key(package, provider="openrouter", model="model-a")
    package.current_logs = "ERROR connection refused"
    second = build_cache_key(package, provider="openrouter", model="model-a")
    assert first != second


@pytest.mark.asyncio
async def test_cache_roundtrip_regenerates_report_identity(package, report):
    redis = MemoryRedis()
    cache = AnalysisCache(client=redis, ttl_seconds=900)

    await cache.set("test-key", report)
    cached = await cache.get("test-key")

    assert cached is not None
    assert cached.incident_id != report.incident_id
    assert cached.created_at != report.created_at
    assert cached.likely_root_cause == report.likely_root_cause
    assert redis.expirations["test-key"] == 900


@pytest.mark.asyncio
async def test_invalid_cached_report_is_deleted():
    redis = MemoryRedis()
    redis.values["bad"] = json.dumps({"incident_summary": "invalid"})
    cache = AnalysisCache(client=redis)

    assert await cache.get("bad") is None
    assert "bad" not in redis.values
