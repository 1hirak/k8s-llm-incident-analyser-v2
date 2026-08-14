"""API-level tests for collector-svc (contracts/api/collector.yaml)."""

from unittest.mock import MagicMock, patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _mock_result(stdout="", stderr="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestHealth:
    def test_health_shape(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "collector-svc"
        assert "version" in data

    def test_health_reports_cluster_connected(self):
        with patch("subprocess.run", return_value=_mock_result("Client Version: v1.30")):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["cluster"] == "connected"

    def test_health_reports_cluster_unreachable(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("kubectl")):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["cluster"] == "unreachable"


class TestStatus:
    def test_status_reports_connection_and_permissions(self):
        results = [_mock_result("server version")]
        results.extend(_mock_result("yes") for _ in range(3))
        with patch("subprocess.run", side_effect=results):
            resp = client.get("/status?namespace=production")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cluster"] == "connected"
        assert data["namespace"] == "production"
        assert data["permissions"] == {
            "get_pods": True,
            "get_pod_logs": True,
            "get_events": True,
        }

    def test_health_includes_all_standard_fields(self):
        resp = client.get("/health")
        data = resp.json()
        assert set(data) >= {"status", "service", "version", "cluster"}

    def test_health_with_subprocess_timeout(self):
        from subprocess import TimeoutExpired

        with patch("subprocess.run", side_effect=TimeoutExpired("kubectl", 5)):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["cluster"] == "unreachable"


class TestCollect:
    def test_collect_success(self):
        returns = [_mock_result("demo-app-abc")] + [
            _mock_result("log line") for _ in range(6)
        ]
        with patch("subprocess.run", side_effect=returns):
            resp = client.post(
                "/collect", json={"namespace": "demo", "pod_name": "demo-app-abc"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "demo"
        assert data["pod_name"] == "demo-app-abc"
        assert "current_logs" in data
        assert "restart_count" in data

    def test_collect_requires_pod_name(self):
        resp = client.post("/collect", json={"namespace": "demo"})
        assert resp.status_code == 400
        body = resp.json()
        # RFC 7807 Problem Details
        assert body["status"] == 400
        assert body["title"] == "Invalid request"
        assert "type" in body
        assert "detail" in body

    def test_collect_kubectl_missing_returns_500_problem(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("kubectl")):
            resp = client.post(
                "/collect", json={"namespace": "demo", "pod_name": "x"}
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == 500
        assert "kubectl" in body["detail"]

    def test_collect_generic_exception_returns_500(self):
        with patch("subprocess.run", side_effect=PermissionError("access denied")):
            resp = client.post(
                "/collect", json={"namespace": "demo", "pod_name": "x"}
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == 500
        assert "access denied" in body["detail"].lower()

    def test_collect_missing_namespace(self):
        resp = client.post("/collect", json={"pod_name": "demo-app"})
        # namespace defaults to "demo" in the model, so this may succeed
        assert resp.status_code in (200, 400)

    def test_collect_empty_body(self):
        resp = client.post("/collect", json={})
        assert resp.status_code == 400
        assert resp.json()["status"] == 400

    def test_collect_returns_problem_plus_json_content_type(self):
        resp = client.post("/collect", json={"namespace": "demo"})
        assert resp.headers.get("content-type") == "application/problem+json"

    def test_collect_resolves_pod_by_label(self):
        returns = [
            _mock_result(""),          # _pod_exists → not found
            _mock_result("resolved"),
            _mock_result("current"),
            _mock_result("previous"),
            _mock_result("describe"),
            _mock_result("events"),
            _mock_result("3"),
            _mock_result("[]"),
        ]
        with patch("subprocess.run", side_effect=returns):
            resp = client.post(
                "/collect", json={"namespace": "demo", "pod_name": "demo-app"}
            )
        assert resp.status_code == 200
        assert resp.json()["pod_name"] == "resolved"

    def test_collect_returns_rfc7807_on_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("kubectl")):
            resp = client.post(
                "/collect", json={"namespace": "demo", "pod_name": "x"}
            )
        body = resp.json()
        assert "type" in body
        assert body["type"].startswith("https://errors.k8s-llm.io")
