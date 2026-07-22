"""API-level tests for llm-svc (contracts/api/llm.yaml)."""

import os
from unittest.mock import patch

import pytest
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture
def evidence_package() -> dict:
    return {
        "namespace": "demo",
        "pod_name": "demo-app-abc",
        "current_logs": "ERROR Missing DATABASE_URL",
        "previous_logs": "WARN previous log",
        "pod_status_summary": "Status: CrashLoopBackOff",
        "k8s_events_filtered": "Warning BackOff restarting",
        "restart_count": 3,
    }


class TestHealth:
    def test_health_includes_provider_and_model(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "llm-svc"
        assert data["provider"] == "mock"
        assert data["model"] == "(none)"


class TestProviders:
    def test_lists_all_four_providers(self):
        resp = client.get("/providers")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = {item["id"] for item in items}
        assert ids == {"mock", "openai", "anthropic", "deepseek"}

    def test_mock_always_available(self):
        with patch.dict(os.environ, {}, clear=True):
            resp = client.get("/providers")
        items = {item["id"]: item for item in resp.json()["items"]}
        assert items["mock"]["available"] is True

    def test_availability_reflects_api_keys(self):
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True
        ):
            resp = client.get("/providers")
        items = {item["id"]: item for item in resp.json()["items"]}
        assert items["deepseek"]["available"] is True
        assert items["openai"]["available"] is False


class TestAnalyse:
    def test_analyse_mock_returns_report(self, evidence_package):
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 200
        data = resp.json()
        assert data["failure_category"] == "config"
        assert data["incident_id"]
        assert data["created_at"]
        assert len(data["supporting_evidence"]) >= 1
        assert 0.0 <= data["confidence"] <= 1.0

    def test_analyse_invalid_body_returns_400(self):
        resp = client.post("/analyse", json={"namespace": "demo"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == 400
        assert body["title"] == "Invalid request"

    def test_analyse_provider_error_returns_500_problem(
        self, evidence_package
    ):
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-fake"},
            clear=True,
        ):
            resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == 500
        assert "type" in body

    def test_analyse_unknown_provider_falls_back_to_mock(
        self, evidence_package
    ):
        with patch.dict(
            os.environ, {"LLM_PROVIDER": "nonexistent"}, clear=True,
        ):
            resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 200
        data = resp.json()
        assert "failure_category" in data

    def test_analyse_mock_detects_imagepull(
        self, evidence_package
    ):
        pkg = dict(evidence_package)
        pkg["current_logs"] = "ImagePullBackOff error on k8s"
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            resp = client.post("/analyse", json=pkg)
        assert resp.json()["failure_category"] == "image"

    def test_analyse_mock_detects_oom(
        self, evidence_package
    ):
        pkg = dict(evidence_package)
        pkg["pod_status_summary"] = "OOMKilled container demo-app"
        pkg["current_logs"] = ""
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            resp = client.post("/analyse", json=pkg)
        assert resp.json()["failure_category"] == "resource"

    def test_providers_llm_model_env(self):
        with patch.dict(
            os.environ,
            {"LLM_MODEL": "gpt-4o", "LLM_PROVIDER": "mock"},
            clear=True,
        ):
            resp = client.get("/health")
        assert resp.json()["model"] == "gpt-4o"

    def test_providers_list_uses_llm_model_env(self):
        with patch.dict(
            os.environ,
            {"LLM_MODEL": "custom-model", "LLM_PROVIDER": "mock"},
            clear=True,
        ):
            resp = client.get("/providers")
        for item in resp.json()["items"]:
            assert item["model"] == "custom-model"
