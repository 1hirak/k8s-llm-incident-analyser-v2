"""Redis job store — implements contracts/database/redis_schema.md.

Key patterns:
  job:{job_id}          Hash   — job state (TTL 24h)
  job:queue             List   — job queue (LPUSH/BRPOP; v2 worker scaling)
  job:{job_id}:events   Pub/Sub — SSE event fanout channel

Listing uses SCAN over job hashes (keys matching job:<uuid>). At
dissertation scale (~10 jobs/day with 24h TTL) this is bounded and cheap.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import redis.asyncio as redis
from k8s_llm_shared import (
    IncidentReport,
    JobState,
    SseDoneEvent,
    SseFailedEvent,
    SseStageEvent,
    utc_now_iso,
)

JOB_TTL_SECONDS = 86400  # 24 hours
JOB_QUEUE_KEY = "job:queue"
_JOB_KEY_RE = re.compile(r"^job:[0-9a-fA-F-]{36}$")


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def _events_channel(job_id: str) -> str:
    return f"job:{job_id}:events"


class JobStore:
    def __init__(self, client: redis.Redis):
        self._r = client

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    async def create(
        self, job_id: str, namespace: str, pod_name: str, target_kind: str = "Pod"
    ) -> None:
        now = utc_now_iso()
        await self._r.hset(
            _job_key(job_id),
            mapping={
                "job_id": job_id,
                "namespace": namespace,
                "pod_name": pod_name,
                "target_kind": target_kind,
                "status": "queued",
                "created_at": now,
                "updated_at": now,
            },
        )
        await self._r.expire(_job_key(job_id), JOB_TTL_SECONDS)
        await self._r.lpush(JOB_QUEUE_KEY, job_id)

    async def clear_queue(self) -> int:
        """Remove pending queue entries without touching report history."""
        count = await self._r.llen(JOB_QUEUE_KEY)
        await self._r.delete(JOB_QUEUE_KEY)
        return int(count)

    # ------------------------------------------------------------------
    # State transitions (each publishes an SSE event)
    # ------------------------------------------------------------------

    async def transition(self, job_id: str, status: str, stage: str) -> None:
        now = utc_now_iso()
        await self._r.hset(
            _job_key(job_id),
            mapping={"status": status, "stage": stage, "updated_at": now},
        )
        event = SseStageEvent(
            job_id=job_id, status=status, stage=stage, updated_at=now  # type: ignore[arg-type]
        )
        await self._publish(job_id, event.model_dump())

    async def complete(
        self,
        job_id: str,
        incident_id: str,
        latency_ms: int,
        report: IncidentReport,
    ) -> None:
        now = utc_now_iso()
        await self._r.hset(
            _job_key(job_id),
            mapping={
                "status": "done",
                "incident_id": incident_id,
                "latency_ms": latency_ms,
                "updated_at": now,
            },
        )
        event = SseDoneEvent(
            job_id=job_id,
            incident_id=incident_id,
            failure_category=report.failure_category,
            severity=report.severity,
            active_error=report.active_error,
            latency_ms=latency_ms,
        )
        await self._publish(job_id, event.model_dump())

    async def fail(self, job_id: str, error: str, latency_ms: int) -> None:
        now = utc_now_iso()
        await self._r.hset(
            _job_key(job_id),
            mapping={
                "status": "failed",
                "error": error[:500],
                "latency_ms": latency_ms,
                "updated_at": now,
            },
        )
        event = SseFailedEvent(job_id=job_id, error=error[:500], latency_ms=latency_ms)
        await self._publish(job_id, event.model_dump())

    async def _publish(self, job_id: str, payload: dict[str, Any]) -> None:
        await self._r.publish(_events_channel(job_id), json.dumps(payload))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get(self, job_id: str) -> Optional[JobState]:
        data = await self._r.hgetall(_job_key(job_id))
        if not data:
            return None
        return self._to_state(data)

    async def list(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[JobState], int]:
        keys = [
            key
            async for key in self._r.scan_iter(match="job:*")
            if _JOB_KEY_RE.match(key)
        ]
        states = []
        for key in keys:
            data = await self._r.hgetall(key)
            if data:
                states.append(self._to_state(data))
        states.sort(key=lambda s: s.created_at, reverse=True)
        if status:
            states = [s for s in states if s.status == status]
        return states[offset : offset + limit], len(states)

    @staticmethod
    def _to_state(data: dict[str, Any]) -> JobState:
        latency = data.get("latency_ms")
        return JobState(
            job_id=data["job_id"],
            namespace=data["namespace"],
            pod_name=data["pod_name"],
            target_kind=data.get("target_kind", "Pod"),
            status=data["status"],  # type: ignore[arg-type]
            stage=data.get("stage") or None,
            incident_id=data.get("incident_id") or None,
            latency_ms=int(latency) if latency not in (None, "") else None,
            error=data.get("error") or None,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    # ------------------------------------------------------------------
    # Pub/Sub
    # ------------------------------------------------------------------

    def subscribe(self, job_id: str):
        """Return a pubsub object subscribed to the job's event channel."""
        pubsub = self._r.pubsub()
        return pubsub, _events_channel(job_id)
