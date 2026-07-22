"""scenario-svc — fault scenario management service.

Implements contracts/api/scenario.yaml. Lists available fault scenarios,
applies faults via kubectl patch, and resets the cluster to the healthy
baseline. The only service that needs Kubernetes write RBAC.
"""

import os
from functools import lru_cache
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.scenarios import (
    ClusterUnreachableError,
    KubectlError,
    ScenarioConflictError,
    ScenarioManager,
    ScenarioNotFoundError,
)

log = structlog.get_logger()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _scenarios_dir() -> str:
    env = os.environ.get("SCENARIOS_DIR")
    if env:
        return env
    return str(_repo_root() / "k8s" / "scenarios")


def _base_dir() -> str:
    env = os.environ.get("BASE_DIR")
    if env:
        return env
    return str(_repo_root() / "k8s" / "base")


def _ground_truth_dir() -> str:
    env = os.environ.get("GROUND_TRUTH_DIR")
    if env:
        return env
    return str(_repo_root() / "evaluation" / "ground_truth")


@lru_cache(maxsize=1)
def _manager() -> ScenarioManager:
    return ScenarioManager(
        scenarios_dir=_scenarios_dir(),
        base_dir=_base_dir(),
        namespace=os.environ.get("K8S_NAMESPACE", "demo"),
        ground_truth_dir=_ground_truth_dir(),
    )


app = FastAPI(
    title="scenario-svc",
    description="Fault scenario management (kubectl patch apply/reset)",
    version="0.1.0",
)
add_error_handlers(app)


@app.get("/health", tags=["Health"])
def health() -> dict:
    cluster = "connected" if _manager().check_connectivity() else "unreachable"
    return health_payload("scenario-svc", cluster=cluster)


@app.get("/scenarios", tags=["Scenarios"])
def list_scenarios() -> dict:
    items = _manager().list_scenarios()
    return {"items": [item.model_dump(exclude_none=True) for item in items]}


@app.post("/scenarios/{scenario_id}/apply", tags=["Scenarios"])
def apply_scenario(scenario_id: str) -> dict:
    log.info("scenario_apply_requested", scenario=scenario_id)
    if not _manager().check_connectivity():
        raise HTTPException(
            status_code=503,
            detail="Kubernetes cluster is not running or unreachable. "
                   "Start minikube and try again.",
        )
    try:
        description = _manager().apply(scenario_id)
    except ScenarioNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ScenarioConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ClusterUnreachableError as e:
        raise HTTPException(
            status_code=503,
            detail="Kubernetes cluster is not running or unreachable. "
                   "Start minikube and try again.",
        ) from e
    except KubectlError as e:
        raise HTTPException(
            status_code=500, detail=f"kubectl patch failed: {e}"
        ) from e
    log.info("scenario_applied", scenario=scenario_id)
    return {
        "applied": True,
        "scenario_id": scenario_id,
        "fault_description": description,
    }


@app.post("/scenarios/reset", tags=["Scenarios"])
def reset_scenarios() -> dict:
    log.info("scenario_reset_requested")
    if not _manager().check_connectivity():
        raise HTTPException(
            status_code=503,
            detail="Kubernetes cluster is not running or unreachable. "
                   "Start minikube and try again.",
        )
    try:
        _manager().reset()
    except ClusterUnreachableError as e:
        raise HTTPException(
            status_code=503,
            detail="Kubernetes cluster is not running or unreachable. "
                   "Start minikube and try again.",
        ) from e
    except KubectlError as e:
        raise HTTPException(
            status_code=500, detail=f"kubectl reset failed: {e}"
        ) from e
    log.info("scenario_reset_complete")
    return {"reset": True}
