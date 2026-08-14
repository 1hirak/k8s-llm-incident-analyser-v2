"""API-level tests for gateway-svc (contracts/api/gateway.yaml)."""

from .conftest import INCIDENT_ID, JOB_ID, SSE_BODY


class TestHealth:
    def test_health_includes_provider(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "gateway-svc"
        assert data["provider"] == "mock"


class TestJobsProxy:
    def test_create_job_returns_202(self, api_client):
        resp = api_client.post(
            "/api/jobs", json={"namespace": "demo", "pod_name": "demo-app"}
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == JOB_ID
        assert data["status"] == "queued"

    def test_list_jobs(self, api_client):
        resp = api_client.get("/api/jobs?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["job_id"] == JOB_ID

    def test_get_job(self, api_client):
        resp = api_client.get(f"/api/jobs/{JOB_ID}")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == JOB_ID

    def test_get_job_404_passthrough(self, api_client):
        from k8s_llm_shared import new_id

        resp = api_client.get(f"/api/jobs/{new_id()}")
        assert resp.status_code == 404
        body = resp.json()
        assert body["status"] == 404
        assert body["title"] == "Not found"

    def test_cancel_job(self, api_client):
        resp = api_client.post(f"/api/jobs/{JOB_ID}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert resp.json()["error"] == "Diagnosis cancelled by user"

    def test_cancel_active_jobs(self, api_client):
        resp = api_client.post("/api/jobs/active/cancel")
        assert resp.status_code == 200
        assert resp.json() == {"cancelled": 1}


class TestJobsStreamProxy:
    def test_sse_stream_passthrough(self, api_client):
        with api_client.stream("GET", f"/api/jobs/{JOB_ID}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers.get("x-accel-buffering") == "no"
            body = "".join(resp.iter_text())
        assert "event: stage" in body
        assert "event: done" in body
        assert INCIDENT_ID in body
        assert body == SSE_BODY


class TestReportsProxy:
    def test_list_reports(self, api_client):
        resp = api_client.get("/api/reports?category=config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["failure_category"] == "config"

    def test_get_report(self, api_client):
        resp = api_client.get(f"/api/reports/{INCIDENT_ID}")
        assert resp.status_code == 200
        assert resp.json()["incident_id"] == INCIDENT_ID


class TestStatsProxy:
    def test_stats(self, api_client):
        resp = api_client.get("/api/stats?range=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reports"] == 1
        assert data["category_counts"] == {"config": 1}


class TestScenariosProxy:
    def test_list_scenarios(self, api_client):
        resp = api_client.get("/api/scenarios")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["scenario_id"] == "05-oom"

    def test_apply_scenario(self, api_client):
        resp = api_client.post("/api/scenarios/05-oom/apply")
        assert resp.status_code == 200
        assert resp.json()["applied"] is True

    def test_reset_scenarios(self, api_client):
        resp = api_client.post("/api/scenarios/reset")
        assert resp.status_code == 200
        assert resp.json()["reset"] is True


class TestSettingsProxy:
    def test_get_settings(self, api_client):
        resp = api_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "mock"
        assert data["source"] == "env"
        ids = {p["id"] for p in data["providers"]}
        assert ids == {"mock", "openai", "anthropic", "deepseek", "openrouter"}

    def test_save_settings(self, api_client):
        resp = api_client.post(
            "/api/settings",
            json={"provider": "openai", "api_key": "sk-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["source"] == "file"
        assert "sk-secret" not in str(data)

    def test_list_settings_providers(self, api_client):
        resp = api_client.get("/api/settings/providers")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = {item["id"] for item in items}
        assert ids == {"mock", "openai", "anthropic", "deepseek", "openrouter"}
        openai_item = next(i for i in items if i["id"] == "openai")
        assert openai_item["available"] is False


class TestRemediationProxy:
    def test_create_remediation(self, api_client):
        resp = api_client.post(
            "/api/remediations",
            json={
                "action": {
                    "action_type": "rollout_restart",
                    "namespace": "demo",
                    "deployment_name": "demo-app",
                }
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"


class TestGatewayAuth:
    def test_configured_token_rejects_missing_credentials(self, api_client, monkeypatch):
        import app.main as main

        monkeypatch.setattr(main, "GATEWAY_API_TOKEN", "test-token")
        resp = api_client.get("/api/stats")
        assert resp.status_code == 401
        assert resp.json()["title"] == "Authentication required"

    def test_configured_token_allows_health(self, api_client, monkeypatch):
        import app.main as main

        monkeypatch.setattr(main, "GATEWAY_API_TOKEN", "test-token")
        resp = api_client.get("/health")
        assert resp.status_code == 200


class TestRateLimit:
    def test_rate_limit_returns_429_problem(self, api_client):
        from app.main import RATE_LIMIT_PER_MINUTE

        last_resp = None
        for _ in range(RATE_LIMIT_PER_MINUTE + 5):
            last_resp = api_client.get("/api/stats")
        assert last_resp.status_code == 429
        body = last_resp.json()
        assert body["status"] == 429
        assert body["title"] == "Rate limit exceeded"

    def test_health_not_rate_limited(self, api_client):
        # Health is exempt; many calls must never 429
        for _ in range(70):
            resp = api_client.get("/health")
        assert resp.status_code == 200


class TestCors:
    def test_cors_headers_present(self, api_client):
        resp = api_client.options(
            "/api/jobs",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "*"
