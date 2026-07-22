"""orchestrator-svc — analysis pipeline coordinator.

Implements contracts/api/orchestrator.yaml. Owns the job lifecycle:
creates jobs in Redis, coordinates collector → processor → llm →
reports, publishes SSE events via Redis pub/sub, and archives terminal
job state to reports-svc.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import redis.asyncio as redis
import structlog
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from k8s_llm_shared import (
    AnalysisRequest,
    JobCreated,
    SaveJobRequest,
    new_id,
)
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.pipeline import Pipeline
from app.store import JobStore

log = structlog.get_logger()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
COLLECTOR_URL = os.environ.get("COLLECTOR_URL", "http://localhost:8002")
PROCESSOR_URL = os.environ.get("PROCESSOR_URL", "http://localhost:8003")
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8004")
REPORTS_URL = os.environ.get("REPORTS_URL", "http://localhost:8005")
PIPELINE_TIMEOUT = int(os.environ.get("PIPELINE_TIMEOUT", "120"))

TERMINAL_STATUSES = ("done", "failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.redis.aclose()
    await app.state.http.aclose()


app = FastAPI(
    title="orchestrator-svc",
    description="Analysis pipeline coordinator (jobs, SSE, Redis state)",
    version="0.1.0",
    lifespan=lifespan,
)
add_error_handlers(app)


def _store(request: Request) -> JobStore:
    return JobStore(request.app.state.redis)


def _pipeline(request: Request) -> Pipeline:
    return Pipeline(
        store=_store(request),
        http=request.app.state.http,
        collector_url=COLLECTOR_URL,
        processor_url=PROCESSOR_URL,
        llm_url=LLM_URL,
        reports_url=REPORTS_URL,
        timeout_seconds=PIPELINE_TIMEOUT,
    )


@app.get("/health", tags=["Health"])
def health() -> dict:
    return health_payload("orchestrator-svc")


@app.post("/jobs", response_model=JobCreated, status_code=202, tags=["Jobs"])
async def create_job(request: AnalysisRequest, req: Request) -> JobCreated:
    """Create a job, queue it, and run the pipeline in the background."""
    store = _store(req)
    job_id = new_id()
    await store.create(job_id, request.namespace, request.pod_name)
    log.info(
        "job_created", job_id=job_id,
        namespace=request.namespace, pod=request.pod_name,
    )

    # Durable snapshot (best-effort)
    pipeline = _pipeline(req)
    await pipeline._archive_job(
        SaveJobRequest(
            job_id=job_id,
            namespace=request.namespace,
            pod_name=request.pod_name,
            status="queued",
        )
    )

    async def _run_with_timeout() -> None:
        try:
            await asyncio.wait_for(
                pipeline.run(job_id, request.namespace, request.pod_name),
                timeout=PIPELINE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            await store.fail(job_id, f"Pipeline exceeded {PIPELINE_TIMEOUT}s", 0)
        except Exception as e:
            log.error("pipeline_task_crashed", job_id=job_id, error=str(e))

    asyncio.create_task(_run_with_timeout())
    return JobCreated(job_id=job_id, status="queued")


@app.get("/jobs", tags=["Jobs"])
async def list_jobs(
    req: Request,
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, count = await _store(req).list(
        status=status, limit=limit, offset=offset
    )
    return {
        "items": [item.model_dump() for item in items],
        "count": count,
        "limit": limit,
        "offset": offset,
    }


@app.get("/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str, req: Request) -> dict:
    job = await _store(req).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.model_dump()


@app.get("/jobs/{job_id}/stream", tags=["Jobs"])
async def stream_job(job_id: str, req: Request) -> StreamingResponse:
    """SSE stream of job events (stage transitions, done, failed).

    Replays the current state immediately (so late subscribers know where
    the job stands), then forwards live pub/sub messages until the job
    reaches a terminal state.
    """
    store = _store(req)
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        # 1. Replay current state
        if job.status in TERMINAL_STATUSES:
            yield _format_terminal_event(job)
            return
        stage_payload = {
            "event": "stage",
            "job_id": job.job_id,
            "status": job.status,
            "stage": job.stage or "",
            "updated_at": job.updated_at,
        }
        yield f"event: stage\ndata: {json.dumps(stage_payload)}\n\n"

        # 2. Forward live events until terminal
        pubsub, channel = store.subscribe(job_id)
        try:
            await pubsub.subscribe(channel)
            while True:
                if await req.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue
                payload = json.loads(message["data"])
                event_type = payload.get("event", "stage")
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                if event_type in TERMINAL_STATUSES:
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _format_terminal_event(job) -> str:
    if job.status == "done":
        payload = {
            "event": "done",
            "job_id": job.job_id,
            "status": "done",
            "incident_id": job.incident_id,
            "latency_ms": job.latency_ms,
        }
        return f"event: done\ndata: {json.dumps(payload)}\n\n"
    payload = {
        "event": "failed",
        "job_id": job.job_id,
        "status": "failed",
        "error": job.error,
        "latency_ms": job.latency_ms,
    }
    return f"event: failed\ndata: {json.dumps(payload)}\n\n"
