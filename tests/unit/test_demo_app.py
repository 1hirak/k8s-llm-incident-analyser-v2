import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

DEMO_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "demo-app")


def _import_demo_app():
    saved_path = sys.path[:]
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith("app")}
    for k in list(sys.modules.keys()):
        if k.startswith("app"):
            del sys.modules[k]
    sys.path.insert(0, DEMO_APP_PATH)
    try:
        from app.main import app
        return app
    finally:
        sys.path = saved_path
        for k in list(sys.modules.keys()):
            if k.startswith("app"):
                del sys.modules[k]
        sys.modules.update(saved_modules)


@pytest.fixture
def client():
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///./test.db"}, clear=True):
        app = _import_demo_app()
        return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadyEndpoint:
    def test_ready_returns_ok_when_db_available(self, client):
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"ready": True}

    def test_ready_raises_error_when_db_unavailable(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://unavailable:5432/db"},
            clear=True,
        ):
            app = _import_demo_app()
            test_client = TestClient(app)
            with pytest.raises(RuntimeError):
                test_client.get("/ready")


class TestFaultEndpoints:
    def test_fault_crash_raises_error(self, client):
        with pytest.raises(ZeroDivisionError):
            client.get("/fault/crash")

    def test_fault_oom_returns_allocated(self, client):
        response = client.get("/fault/oom")
        assert response.status_code == 200
        data = response.json()
        assert "allocated" in data
        assert data["allocated"] == 600
