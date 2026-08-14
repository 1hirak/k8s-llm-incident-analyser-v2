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
    def test_lists_all_providers(self):
        resp = client.get("/providers")
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = {item["id"] for item in items}
        assert ids == {"mock", "openai", "anthropic", "deepseek", "openrouter"}

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
        explanation = data["analysis_explanation"]
        assert explanation["rationale"]
        assert explanation["key_signals"]
        assert explanation["uncertainty"]
        assert explanation["input_summary"]["current_log_lines"] == 1
        assert explanation["input_summary"]["redaction_applied"] is True

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

    def test_analyse_missing_api_key_returns_500_config_error(
        self, evidence_package
    ):
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek"},
            clear=True,
        ):
            resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == 500
        assert "DEEPSEEK_API_KEY" in body["detail"]

    def test_analyse_truncation_returns_502(self, evidence_package):
        from app.llm import deepseek_provider as ds_mod

        async def fake_analyse(self, package):
            from app.llm.errors import LLMTruncationError
            raise LLMTruncationError(
                "DeepSeek returned truncated JSON (finish_reason=length)"
            )

        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            with patch.object(
                ds_mod.DeepSeekProvider, "analyse", fake_analyse
            ):
                resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 502
        body = resp.json()
        assert body["status"] == 502
        assert "finish_reason=length" in body["detail"]

    def test_analyse_rate_limit_returns_429(self, evidence_package):
        from app.llm import deepseek_provider as ds_mod

        async def fake_analyse(self, package):
            from app.llm.errors import LLMRateLimitError
            raise LLMRateLimitError("DeepSeek rate limit hit: slow down")

        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            with patch.object(
                ds_mod.DeepSeekProvider, "analyse", fake_analyse
            ):
                resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 429
        body = resp.json()
        assert body["status"] == 429

    def test_analyse_unavailable_returns_503(self, evidence_package):
        from app.llm import deepseek_provider as ds_mod

        async def fake_analyse(self, package):
            from app.llm.errors import LLMUnavailableError
            raise LLMUnavailableError("DeepSeek returned 502: down")

        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            with patch.object(
                ds_mod.DeepSeekProvider, "analyse", fake_analyse
            ):
                resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == 503

    def test_analyse_invalid_output_returns_502(self, evidence_package):
        from app.llm import deepseek_provider as ds_mod

        async def fake_analyse(self, package):
            from app.llm.errors import LLMInvalidOutputError
            raise LLMInvalidOutputError(
                "DeepSeek returned non-JSON output (finish_reason=stop)"
            )

        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            with patch.object(
                ds_mod.DeepSeekProvider, "analyse", fake_analyse
            ):
                resp = client.post("/analyse", json=evidence_package)
        assert resp.status_code == 502
        body = resp.json()
        assert body["status"] == 502

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
