"""API-level tests for scenario-svc (contracts/api/scenario.yaml)."""

from unittest.mock import MagicMock, patch

import pytest
from app.main import app, _manager
from fastapi.testclient import TestClient

client = TestClient(app)


def ok_result(stdout="patched"):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = 0
    return m


def error_result(returncode=1):
    m = MagicMock()
    m.stdout = ""
    m.stderr = "error from kubectl"
    m.returncode = returncode
    return m


@pytest.fixture(autouse=True)
def clear_active():
    _manager.cache_clear()
    yield
    _manager.cache_clear()


class TestHealth:
    def test_health_shape(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "scenario-svc"

    def test_health_with_cluster_connected(self):
        with patch("subprocess.run", return_value=ok_result("Connected")):
            resp = client.get("/health")
        assert resp.json()["cluster"] == "connected"

    def test_health_with_cluster_unreachable(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("kubectl")):
            resp = client.get("/health")
        assert resp.json()["cluster"] == "unreachable"

    def test_health_includes_all_fields(self):
        resp = client.get("/health")
        data = resp.json()
        assert set(data) >= {"status", "service", "version", "cluster"}


class TestListScenarios:
    def test_lists_scenarios(self):
        resp = client.get("/scenarios")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 25
        ids = [i["scenario_id"] for i in items]
        assert "05-oom" in ids
        oom = next(i for i in items if i["scenario_id"] == "05-oom")
        assert oom["category"] == "resource"
        assert oom["severity"] == "high"
        assert oom["description"]

    def test_all_25_scenarios_returned(self):
        resp = client.get("/scenarios")
        assert len(resp.json()["items"]) == 25

    def test_each_scenario_has_required_fields(self):
        resp = client.get("/scenarios")
        for item in resp.json()["items"]:
            assert "scenario_id" in item
            assert "name" in item
            assert "category" in item
            assert "description" in item


class TestApplyScenario:
    def _patch_connectivity(self):
        m = _manager()
        m.check_connectivity = lambda: True
        return m

    def test_apply_success(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=ok_result()):
            resp = client.post("/scenarios/05-oom/apply")
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is True
        assert data["scenario_id"] == "05-oom"
        assert data["fault_description"]

    def test_apply_not_found(self):
        self._patch_connectivity()
        resp = client.post("/scenarios/99-nope/apply")
        assert resp.status_code == 404
        body = resp.json()
        assert body["status"] == 404

    def test_apply_multiple_scenarios(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=ok_result()):
            first = client.post("/scenarios/05-oom/apply")
            second = client.post("/scenarios/03-crashloop/apply")
        assert first.status_code == 200
        assert second.status_code == 200

    def test_apply_duplicate_returns_409(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=ok_result()):
            client.post("/scenarios/05-oom/apply")
            resp = client.post("/scenarios/05-oom/apply")
        assert resp.status_code == 409
        body = resp.json()
        assert body["status"] == 409
        assert "already applied" in body["detail"].lower()

    def test_apply_with_cluster_unreachable(self):
        manager = _manager()
        original_check = manager.check_connectivity
        manager.check_connectivity = lambda: False
        try:
            resp = client.post("/scenarios/05-oom/apply")
            assert resp.status_code == 503
            assert "Kubernetes cluster" in resp.json()["detail"]
        finally:
            manager.check_connectivity = original_check

    def test_apply_kubectl_error_returns_500(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=error_result()):
            resp = client.post("/scenarios/05-oom/apply")
        assert resp.status_code == 500
        assert resp.json()["status"] == 500


class TestReset:
    def _patch_connectivity(self):
        m = _manager()
        m.check_connectivity = lambda: True
        return m

    def test_reset_success(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=ok_result()):
            client.post("/scenarios/05-oom/apply")
            resp = client.post("/scenarios/reset")
        assert resp.status_code == 200
        assert resp.json()["reset"] is True
        assert _manager().active_scenarios == frozenset()

    def test_reset_when_no_scenario_active(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=ok_result()):
            resp = client.post("/scenarios/reset")
        assert resp.status_code == 200
        assert resp.json()["reset"] is True

    def test_reset_with_cluster_unreachable(self):
        m = _manager()
        original = m.check_connectivity
        m.check_connectivity = lambda: False
        try:
            resp = client.post("/scenarios/reset")
            assert resp.status_code == 503
        finally:
            m.check_connectivity = original

    def test_reset_kubectl_error(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=error_result()):
            resp = client.post("/scenarios/reset")
        assert resp.status_code == 500

    def test_apply_then_reset_then_apply_another(self):
        self._patch_connectivity()
        with patch("subprocess.run", return_value=ok_result()):
            resp1 = client.post("/scenarios/05-oom/apply")
            assert resp1.status_code == 200
            resp2 = client.post("/scenarios/reset")
            assert resp2.status_code == 200
            resp3 = client.post("/scenarios/03-crashloop/apply")
            assert resp3.status_code == 200
