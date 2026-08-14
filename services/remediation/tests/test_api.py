import app.main as main
import fakeredis.aioredis
import pytest
from app.main import app
from fastapi.testclient import TestClient


class FakeManager:
    def check_connectivity(self):
        return True

    def dry_run(self, action):
        return "server-side dry-run output"

    def apply(self, action):
        return "deployment patched\nrollout successful"


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setattr(main, "REMEDIATION_ENABLED", True)
    with TestClient(app) as client:
        app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        app.state.manager = FakeManager()
        yield client


def request_body():
    return {
        "action": {
            "action_type": "rollout_restart",
            "namespace": "demo",
            "deployment_name": "demo-app",
        },
        "requested_by": "alice",
    }


def test_create_then_approve_requires_explicit_confirmation(api_client):
    created = api_client.post("/remediations", json=request_body())
    assert created.status_code == 201
    record = created.json()
    assert record["status"] == "pending"
    assert record["dry_run_output"] == "server-side dry-run output"

    missing_confirmation = api_client.post(
        f"/remediations/{record['remediation_id']}/approve",
        json={"approved_by": "alice", "confirm": False},
    )
    assert missing_confirmation.status_code == 400

    approved = api_client.post(
        f"/remediations/{record['remediation_id']}/approve",
        headers={"X-Operator-Id": "alice"},
        json={"confirm": True},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "applied"
    assert approved.json()["approved_by"] == "alice"


def test_rejected_proposal_cannot_be_approved(api_client):
    created = api_client.post("/remediations", json=request_body())
    remediation_id = created.json()["remediation_id"]
    rejected = api_client.post(
        f"/remediations/{remediation_id}/reject",
        json={"approved_by": "alice"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    approved = api_client.post(
        f"/remediations/{remediation_id}/approve",
        json={"approved_by": "alice", "confirm": True},
    )
    assert approved.status_code == 409
