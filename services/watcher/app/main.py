"""watcher-svc — continuously submits unhealthy pod analyses."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
import structlog
from fastapi import FastAPI
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.watcher import KubernetesWatcher

log = structlog.get_logger()
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8001").rstrip("/")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
WATCH_INTERVAL_SECONDS = max(5, int(os.environ.get("WATCH_INTERVAL_SECONDS", "30")))
WATCH_COOLDOWN_SECONDS = max(60, int(os.environ.get("WATCH_COOLDOWN_SECONDS", "900")))
WATCHER_ENABLED = os.environ.get("WATCHER_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
RESTART_THRESHOLD = max(1, int(os.environ.get("WATCH_RESTART_THRESHOLD", "3")))


def _namespaces() -> tuple[str, ...]:
    raw = os.environ.get("WATCH_NAMESPACES", "demo")
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or ("demo",)


def _watcher(request) -> KubernetesWatcher:
    instance = getattr(request.app.state, "watcher", None)
    if instance is None:
        instance = KubernetesWatcher(
            namespaces=_namespaces(), restart_threshold=RESTART_THRESHOLD
        )
        request.app.state.watcher = instance
    return instance


async def _scan_and_submit(app: FastAPI) -> dict:
    watcher = _watcher(type("Request", (), {"app": app})())
    incidents = await asyncio.to_thread(watcher.scan)
    submitted = 0
    skipped = 0
    errors = 0
    for incident in incidents:
        key = (
            f"watcher:incident:{incident.namespace}:{incident.pod_name}:"
            f"{incident.signature}"
        )
        claimed = await app.state.redis.set(
            key, "1", ex=WATCH_COOLDOWN_SECONDS, nx=True
        )
        if not claimed:
            skipped += 1
            continue
        try:
            response = await app.state.http.post(
                f"{ORCHESTRATOR_URL}/jobs",
                json=incident.as_job_request(),
                timeout=10,
            )
            response.raise_for_status()
            submitted += 1
        except Exception as exc:
            errors += 1
            # Release the claim so a transient orchestrator outage can retry.
            await app.state.redis.delete(key)
            log.warning(
                "watcher_submit_failed",
                namespace=incident.namespace,
                pod=incident.pod_name,
                error=str(exc),
            )
    return {
        "detected": len(incidents),
        "submitted": submitted,
        "skipped": skipped,
        "errors": errors,
    }


async def _watch_loop(app: FastAPI) -> None:
    while True:
        try:
            result = await _scan_and_submit(app)
            log.info("watcher_scan_complete", **result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("watcher_scan_failed", error=str(exc))
        await asyncio.sleep(WATCH_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)
    app.state.http = httpx.AsyncClient()
    app.state.watcher = KubernetesWatcher(
        namespaces=_namespaces(), restart_threshold=RESTART_THRESHOLD
    )
    app.state.watch_task = (
        asyncio.create_task(_watch_loop(app)) if WATCHER_ENABLED else None
    )
    yield
    if app.state.watch_task is not None:
        app.state.watch_task.cancel()
        try:
            await app.state.watch_task
        except asyncio.CancelledError:
            pass
    await app.state.redis.aclose()
    await app.state.http.aclose()


app = FastAPI(
    title="watcher-svc",
    description="Read-only Kubernetes unhealthy workload watcher",
    version="0.1.0",
    lifespan=lifespan,
)
add_error_handlers(app)


@app.get("/health", tags=["Health"])
def health() -> dict:
    watcher = getattr(app.state, "watcher", None)
    cluster = "connected" if watcher and watcher.check_connectivity() else "unreachable"
    payload = health_payload("watcher-svc", cluster=cluster)
    payload.update(
        {
            "enabled": WATCHER_ENABLED,
            "namespaces": list(_namespaces()),
            "interval_seconds": WATCH_INTERVAL_SECONDS,
        }
    )
    return payload


@app.post("/scan", tags=["Watcher"])
async def scan() -> dict:
    """Run one scan immediately; useful for installation checks and operators."""
    return await _scan_and_submit(app)
