"""API-level tests for processor-svc (contracts/api/processor.yaml)."""

from unittest.mock import patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _raw_evidence(**overrides) -> dict:
    data = {
        "namespace": "demo",
        "pod_name": "demo-app-abc",
        "current_logs": (
            "2025-01-01T00:00:00Z INFO GET /health\n"
            + "\n".join(
                f"2025-01-01T00:00:{i:02d}Z INFO routine line {i}"
                for i in range(1, 10)
            )
            + "\n2025-01-01T00:00:11Z ERROR Database connection refused\n"
            "2025-01-01T00:00:12Z INFO password=supersecret123"
        ),
        "previous_logs": "",
        "pod_status": "Status: CrashLoopBackOff",
        "k8s_events": (
            "10s Normal Scheduled pod/demo-app Node assigned\n"
            "10s Warning BackOff pod/demo-app Back-off restarting"
        ),
        "restart_count": 3,
        "container_states": [],
    }
    data.update(overrides)
    return data


class TestHealth:
    def test_health_shape(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "processor-svc"

    def test_health_includes_all_fields(self):
        resp = client.get("/health")
        data = resp.json()
        assert set(data) >= {"status", "service", "version"}


class TestProcess:
    def test_process_filters_and_redacts(self):
        resp = client.post("/process", json=_raw_evidence())
        assert resp.status_code == 200
        data = resp.json()

        # Contract shape
        assert data["namespace"] == "demo"
        assert data["pod_name"] == "demo-app-abc"
        assert data["restart_count"] == 3

        # Signal kept, noise removed
        assert "connection refused" in data["current_logs"]
        assert "GET /health" not in data["current_logs"]

        # Secrets redacted
        assert "supersecret123" not in data["current_logs"]
        assert "[PASSWORD=REDACTED]" in data["current_logs"]

        # Events filtered to warnings/signals
        assert "Warning BackOff" in data["k8s_events_filtered"]
        assert "Normal Scheduled" not in data["k8s_events_filtered"]

    def test_process_truncates_pod_status(self):
        resp = client.post(
            "/process", json=_raw_evidence(pod_status="x" * 5000)
        )
        assert resp.status_code == 200
        assert len(resp.json()["pod_status_summary"]) <= 2000

    def test_process_invalid_body_returns_400_problem(self):
        resp = client.post("/process", json={"namespace": "demo"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["status"] == 400
        assert body["title"] == "Invalid request"

    def test_process_empty_logs(self):
        resp = client.post(
            "/process",
            json=_raw_evidence(current_logs="", previous_logs=""),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_logs"] == ""
        assert data["previous_logs"] == ""

    def test_process_empty_events(self):
        resp = client.post(
            "/process", json=_raw_evidence(k8s_events="")
        )
        assert resp.status_code == 200
        assert resp.json()["k8s_events_filtered"] == ""

    def test_process_noisy_logs_all_filtered(self):
        resp = client.post(
            "/process",
            json=_raw_evidence(
                current_logs="\n".join(
                    [f"GET /health {i}" for i in range(10)]
                ),
            ),
        )
        assert resp.status_code == 200
        assert resp.json()["current_logs"] == ""

    def test_process_all_redaction_types_together(self):
        logs = (
            "ERROR startup failed\n"
            "password=admin123 DB: postgres://u:p@h/db "
            "email=admin@example.com api_key=abcdef1234567890abcdef12"
        )
        resp = client.post(
            "/process",
            json=_raw_evidence(current_logs=logs),
        )
        assert resp.status_code == 200
        data = resp.json()["current_logs"]
        assert "[PASSWORD=REDACTED]" in data
        assert "[DB_URL=REDACTED]" in data
        assert "[EMAIL=REDACTED]" in data
        assert "[API_KEY=REDACTED]" in data
        assert "admin123" not in data
        assert "postgres://u:p@h/db" not in data

    def test_process_returns_rfc7807_on_error(self):
        with patch("app.preprocessor.LogPreprocessor.process", side_effect=ValueError("preprocess failed")):
            resp = client.post(
                "/process",
                json=_raw_evidence(),
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == 500
        assert "preprocess" in body["detail"].lower()
