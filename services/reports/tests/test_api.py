"""API-level tests for reports-svc (contracts/api/reports.yaml)."""

from app.main import app
from fastapi.testclient import TestClient
from k8s_llm_shared import new_id

client = TestClient(app)


def make_report_payload(**overrides) -> dict:
    data = {
        "report": {
            "incident_summary": "Pod demo-app failed to start due to missing config.",
            "likely_root_cause": "The DATABASE_URL environment variable is not set.",
            "affected_component": "demo-app",
            "failure_category": "config",
            "severity": "critical",
            "confidence": 0.9,
            "supporting_evidence": [
                {
                    "source": "pod_log",
                    "pod": "demo-app-abc",
                    "evidence": "FATAL: DATABASE_URL environment variable is not set",
                }
            ],
            "suggested_fix": "Set DATABASE_URL in the deployment env.",
            "recommended_commands": ["kubectl describe pod -n demo demo-app-abc"],
            "human_verification_steps": ["Check environment variables."],
        },
        "namespace": "demo",
        "pod_name": "demo-app-abc",
        "job_id": new_id(),
    }
    data.update(overrides)
    return data


class TestHealth:
    def test_health_shape(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "reports-svc"


class TestReportsEndpoints:
    def test_save_then_get(self):
        resp = client.post("/reports", json=make_report_payload())
        assert resp.status_code == 201
        incident_id = resp.json()["incident_id"]

        resp = client.get(f"/reports/{incident_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == incident_id
        assert data["failure_category"] == "config"
        assert data["created_at"]

    def test_get_missing_returns_404_problem(self):
        resp = client.get(f"/reports/{new_id()}")
        assert resp.status_code == 404
        body = resp.json()
        assert body["status"] == 404
        assert body["title"] == "Not found"

    def test_list_pagination_envelope(self):
        for _ in range(3):
            client.post("/reports", json=make_report_payload())
        resp = client.get("/reports?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0
        summary = data["items"][0]
        # Summary shape excludes nested arrays per contract
        assert "supporting_evidence" not in summary
        assert "namespace" in summary
        assert "failure_category" in summary

    def test_list_filter_by_category(self):
        client.post("/reports", json=make_report_payload())
        payload = make_report_payload()
        payload["report"]["failure_category"] = "resource"
        payload["report"]["severity"] = "high"
        client.post("/reports", json=payload)

        resp = client.get("/reports?category=resource")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["failure_category"] == "resource"


class TestJobsEndpoints:
    def test_upsert_and_list(self):
        job_id = new_id()
        resp = client.post(
            "/jobs",
            json={
                "job_id": job_id,
                "namespace": "demo",
                "pod_name": "demo-app-abc",
                "status": "queued",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["job_id"] == job_id

        resp = client.post(
            "/jobs",
            json={
                "job_id": job_id,
                "namespace": "demo",
                "pod_name": "demo-app-abc",
                "status": "done",
                "latency_ms": 5000,
            },
        )
        assert resp.status_code == 201

        resp = client.get("/jobs?status=done")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["job_id"] == job_id
        assert data["items"][0]["latency_ms"] == 5000


class TestStatsEndpoint:
    def test_stats_shape(self):
        client.post("/reports", json=make_report_payload())
        resp = client.get("/stats?range=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reports"] == 1
        assert data["category_counts"] == {"config": 1}
        assert "mean_latency_ms" in data
        assert "mean_confidence" in data

    def test_stats_rejects_bad_range(self):
        resp = client.get("/stats?range=1y")
        assert resp.status_code == 400
