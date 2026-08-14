"""collector-svc — Kubernetes evidence collection service.

Implements contracts/api/collector.yaml. Wraps kubectl subprocess calls;
stateless (no database, no Redis). The only service that needs read-only
Kubernetes RBAC.
"""

import os

import structlog
from fastapi import FastAPI, HTTPException, Query
from k8s_llm_shared import AnalysisRequest, RawEvidence, TargetKind, TargetListResponse
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.collector import KubernetesCollector

log = structlog.get_logger()

KUBECTL_TIMEOUT = int(os.environ.get("KUBECTL_TIMEOUT", "30"))

app = FastAPI(
    title="collector-svc",
    description="Kubernetes evidence collection service (kubectl wrapper)",
    version="0.1.0",
)
add_error_handlers(app)

collector = KubernetesCollector(timeout=KUBECTL_TIMEOUT)


@app.get("/health", tags=["Health"])
def health() -> dict:
    cluster = "connected" if collector.check_connectivity() else "unreachable"
    return health_payload("collector-svc", cluster=cluster)


@app.get("/status", tags=["Health"])
def status(namespace: str = Query(default="demo", min_length=1)) -> dict:
    """Return connection and read-permission diagnostics for installation checks."""
    return collector.connection_status(namespace)


@app.get("/targets", response_model=TargetListResponse, tags=["Targets"])
def list_targets(
    kind: TargetKind,
    namespace: str | None = Query(default=None),
) -> TargetListResponse:
    """List selectable Kubernetes resources for the diagnosis form."""
    try:
        return TargetListResponse(
            items=collector.list_targets(kind, namespace=namespace)
        )
    except Exception as e:
        log.error("target_list_failed", kind=kind, namespace=namespace, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Target discovery failed: {e}"
        ) from e


@app.post("/collect", response_model=RawEvidence, tags=["Collect"])
def collect_evidence(request: AnalysisRequest) -> RawEvidence:
    """Collect diagnostic evidence from a Kubernetes resource via kubectl."""
    log.info(
        "collect_started",
        namespace=request.namespace,
        target_kind=request.target_kind,
        target=request.pod_name,
    )
    try:
        evidence = collector.collect(
            request.namespace, request.pod_name, request.target_kind
        )
    except FileNotFoundError as e:
        log.error("kubectl_not_found", error=str(e))
        raise HTTPException(
            status_code=500, detail="kubectl binary not found in container"
        ) from e
    except Exception as e:
        log.error("collect_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Collection failed: {e}"
        ) from e
    log.info(
        "collect_complete",
        namespace=evidence.namespace,
        target_kind=evidence.target_kind,
        target=evidence.target_name or evidence.pod_name,
        pods=len(evidence.pod_names),
        restart_count=evidence.restart_count,
    )
    return evidence
