"""collector-svc — Kubernetes evidence collection service.

Implements contracts/api/collector.yaml. Wraps kubectl subprocess calls;
stateless (no database, no Redis). The only service that needs read-only
Kubernetes RBAC.
"""

import os

import structlog
from fastapi import FastAPI, HTTPException
from k8s_llm_shared import AnalysisRequest, RawEvidence
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


@app.post("/collect", response_model=RawEvidence, tags=["Collect"])
def collect_evidence(request: AnalysisRequest) -> RawEvidence:
    """Collect diagnostic evidence from a pod via kubectl."""
    log.info(
        "collect_started", namespace=request.namespace, pod=request.pod_name
    )
    try:
        evidence = collector.collect(request.namespace, request.pod_name)
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
        pod=evidence.pod_name,
        restart_count=evidence.restart_count,
    )
    return evidence
