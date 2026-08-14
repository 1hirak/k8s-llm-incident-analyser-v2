"""remediation-svc — dry-run first, explicit approval, audited apply."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog
from fastapi import FastAPI, HTTPException, Request
from k8s_llm_shared import (
    RemediationApprovalRequest,
    RemediationCreateRequest,
    RemediationRecord,
    new_id,
)
from k8s_llm_shared.web import add_error_handlers, health_payload

from app.manager import RemediationError, RemediationManager

log = structlog.get_logger()
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
REMEDIATION_ENABLED = os.environ.get("REMEDIATION_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
REMEDIATION_MODE = os.environ.get("REMEDIATION_MODE", "approval")
REMEDIATION_TTL = max(300, int(os.environ.get("REMEDIATION_TTL_SECONDS", "86400")))


def _namespaces() -> tuple[str, ...]:
    raw = os.environ.get("REMEDIATION_NAMESPACES", "demo")
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or ("demo",)


def _manager() -> RemediationManager:
    return RemediationManager(allowed_namespaces=_namespaces())


def _key(remediation_id: str) -> str:
    return f"remediation:{remediation_id}"


def _lock_key(remediation_id: str) -> str:
    return f"remediation:{remediation_id}:lock"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)
    app.state.manager = _manager()
    yield
    await app.state.redis.aclose()


app = FastAPI(
    title="remediation-svc",
    description="Approval-gated typed Kubernetes remediation",
    version="0.1.0",
    lifespan=lifespan,
)
add_error_handlers(app)


@app.get("/health", tags=["Health"])
def health() -> dict:
    manager = getattr(app.state, "manager", None)
    cluster = "connected" if manager and manager.check_connectivity() else "unreachable"
    payload = health_payload("remediation-svc", cluster=cluster)
    payload.update(
        {
            "enabled": REMEDIATION_ENABLED,
            "mode": REMEDIATION_MODE,
            "namespaces": list(_namespaces()),
        }
    )
    return payload


@app.post("/remediations", response_model=RemediationRecord, status_code=201)
async def create_remediation(
    request: RemediationCreateRequest, http_request: Request
) -> RemediationRecord:
    if not REMEDIATION_ENABLED:
        raise HTTPException(status_code=503, detail="Remediation is disabled")
    if REMEDIATION_MODE != "approval":
        raise HTTPException(status_code=503, detail="Only approval mode is supported")
    operator = http_request.headers.get("x-operator-id")
    if operator:
        request = request.model_copy(update={"requested_by": operator})
    try:
        dry_run_output = await _run_dry_run(request)
    except RemediationError as exc:
        raise HTTPException(status_code=422, detail=f"Dry-run rejected: {exc}") from exc

    record = RemediationRecord(
        remediation_id=new_id(),
        action=request.action,
        status="pending",
        requested_by=request.requested_by,
        dry_run_output=dry_run_output[:20000],
    )
    await app.state.redis.set(
        _key(record.remediation_id), record.model_dump_json(), ex=REMEDIATION_TTL
    )
    log.info(
        "remediation_dry_run_created",
        remediation_id=record.remediation_id,
        action=request.action.action_type,
        namespace=request.action.namespace,
        deployment=request.action.deployment_name,
        requested_by=request.requested_by,
    )
    return record


async def _run_dry_run(request: RemediationCreateRequest) -> str:
    return await asyncio.to_thread(app.state.manager.dry_run, request.action)


async def _load(remediation_id: str) -> RemediationRecord:
    raw = await app.state.redis.get(_key(remediation_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Remediation not found")
    return RemediationRecord.model_validate(json.loads(raw))


async def _save(record: RemediationRecord) -> None:
    await app.state.redis.set(
        _key(record.remediation_id), record.model_dump_json(), ex=REMEDIATION_TTL
    )


@app.get("/remediations/{remediation_id}", response_model=RemediationRecord)
async def get_remediation(remediation_id: str) -> RemediationRecord:
    return await _load(remediation_id)


@app.post("/remediations/{remediation_id}/reject", response_model=RemediationRecord)
async def reject_remediation(
    remediation_id: str, request: RemediationApprovalRequest, http_request: Request
) -> RemediationRecord:
    operator = http_request.headers.get("x-operator-id")
    if operator:
        request = request.model_copy(update={"approved_by": operator})
    record = await _load(remediation_id)
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="Remediation is no longer pending")
    record.status = "rejected"
    record.approved_by = request.approved_by
    record.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    await _save(record)
    log.info("remediation_rejected", remediation_id=remediation_id, by=request.approved_by)
    return record


@app.post("/remediations/{remediation_id}/approve", response_model=RemediationRecord)
async def approve_remediation(
    remediation_id: str, request: RemediationApprovalRequest, http_request: Request
) -> RemediationRecord:
    if not REMEDIATION_ENABLED:
        raise HTTPException(status_code=503, detail="Remediation is disabled")
    if not request.confirm:
        raise HTTPException(status_code=400, detail="confirm=true is required")
    operator = http_request.headers.get("x-operator-id")
    if operator:
        request = request.model_copy(update={"approved_by": operator})
    record = await _load(remediation_id)
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="Remediation is no longer pending")
    claimed = await app.state.redis.set(_lock_key(remediation_id), "1", ex=180, nx=True)
    if not claimed:
        raise HTTPException(status_code=409, detail="Remediation is already being applied")
    try:
        record.status = "applying"
        record.approved_by = request.approved_by
        record.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await _save(record)
        try:
            result = await asyncio.to_thread(app.state.manager.apply, record.action)
        except RemediationError as exc:
            record.status = "failed"
            record.error = str(exc)[:500]
            record.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            await _save(record)
            log.error("remediation_apply_failed", remediation_id=remediation_id, error=str(exc))
            return record
        record.status = "applied"
        record.result = result[:20000]
        record.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await _save(record)
        log.info("remediation_applied", remediation_id=remediation_id, by=request.approved_by)
        return record
    finally:
        await app.state.redis.delete(_lock_key(remediation_id))
