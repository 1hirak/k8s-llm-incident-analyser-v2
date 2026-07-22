# Redis Schema Contract — K8s LLM Incident Analyser

> **Role**: This document defines the Redis key patterns, data structures,
> and pub/sub channels used by the orchestrator-svc for job state management
> and SSE event fanout. Redis is the primary job-state store; SQLite (in
> reports-svc) is the durable snapshot for historical queries.

---

## 1. Why Redis

The orchestrator needs:

1. **Low-latency job state reads** — the frontend polls `GET /api/jobs/{id}`
   frequently during an active analysis. Redis hash reads are sub-millisecond.
2. **Pub/sub for SSE fanout** — when a job transitions stages, the
   orchestrator publishes an event. The SSE endpoint subscribes to the
   channel and forwards events to the frontend. Multiple SSE clients can
   subscribe to the same job without the orchestrator tracking them.
3. **Simple job queue** — for future worker scaling, a Redis list provides
   `LPUSH`/`BRPOP` queueing without a dedicated message broker.

SQLite is not suitable for these patterns: it has no pub/sub, and its
single-writer model would block SSE clients during job updates.

---

## 2. Key Patterns

### 2.1 Job State Hash

```
Key:    job:{job_id}
Type:   Hash (HSET)
TTL:    24 hours (86400 seconds) — jobs are archived to SQLite after completion
```

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `job_id` | string | `"01938a7b-..."` | UUIDv7 |
| `status` | string | `"collecting"` | One of 7 enum values (see alignment rules) |
| `stage` | string | `"Collecting evidence for demo/demo-app"` | Human-readable detail; nullable |
| `namespace` | string | `"demo"` | K8s namespace |
| `pod_name` | string | `"demo-app-abc123"` | Resolved pod name |
| `incident_id` | string | `"01938a7c-..."` | Populated when status = `done`; absent otherwise |
| `error` | string | `"kubectl timeout"` | Populated when status = `failed`; absent otherwise |
| `latency_ms` | integer | `6800` | Populated on `done` or `failed` |
| `created_at` | string | `"2026-07-21T10:05:33Z"` | ISO 8601 |
| `updated_at` | string | `"2026-07-21T10:05:39Z"` | ISO 8601, updated on every status change |

**Naming**: All hash field names are snake_case per the alignment rules in
`contracts/README.md`.

**TTL rationale**: Active jobs need fast reads. Completed jobs are archived
to the `analysis_jobs` SQLite table by reports-svc. The 24-hour TTL allows
the frontend to poll a recently-completed job's status without hitting the
database, while preventing Redis from accumulating stale state indefinitely.

### 2.2 Job Queue (List)

```
Key:    job:queue
Type:   List (LPUSH / BRPOP)
TTL:    none (persistent list)
```

The orchestrator `LPUSH`es `job_id` onto this list when a new job is created.
In v1, the orchestrator processes jobs synchronously (one at a time, inline
in the request handler). The queue exists for v2 worker scaling: multiple
orchestrator workers can `BRPOP` from the queue to process jobs concurrently.

**v1 behaviour**: The orchestrator both pushes and immediately pops — the
queue is always empty in practice. This is intentional: the data structure
is in place so v2 scaling requires no contract change.

### 2.3 SSE Pub/Sub Channel

```
Pattern: job:{job_id}:events
Type:    Pub/Sub channel (PUBLISH / SUBSCRIBE)
TTL:     n/a (pub/sub channels are ephemeral)
```

The orchestrator `PUBLISH`es JSON messages to this channel on every job
status transition. The SSE endpoint (`GET /api/jobs/{job_id}/stream` on the
gateway) `SUBSCRIBE`s to this channel and forwards each message as an SSE
event to the connected frontend client.

**Message format** (JSON string, snake_case fields):

```json
{
  "event": "stage",
  "job_id": "01938a7b-...",
  "status": "collecting",
  "stage": "Collecting evidence for demo/demo-app",
  "updated_at": "2026-07-21T10:05:34Z"
}
```

See `contracts/api/gateway.yaml` → `GET /api/jobs/{job_id}/stream` for the
full SSE event type definitions (`stage`, `done`, `failed`).

---

## 3. Lifecycle of a Job in Redis

```
1. POST /api/jobs
   → orchestrator generates job_id (UUIDv7)
   → HSET job:{job_id} status=queued namespace=... pod_name=... created_at=...
   → LPUSH job:queue {job_id}
   → returns 202 {job_id, status: "queued"}

2. Orchestrator picks up job (inline in v1):
   → HSET job:{job_id} status=collecting stage="Collecting evidence..."
   → PUBLISH job:{job_id}:events {"event":"stage","status":"collecting",...}
   → calls collector-svc POST /collect

3. Collector returns RawEvidence:
   → HSET job:{job_id} status=processing stage="Filtering logs..."
   → PUBLISH job:{job_id}:events {"event":"stage","status":"processing",...}
   → calls processor-svc POST /process

4. Processor returns EvidencePackage:
   → HSET job:{job_id} status=llm_call stage="Calling DeepSeek..."
   → PUBLISH job:{job_id}:events {"event":"stage","status":"llm_call",...}
   → calls llm-svc POST /analyse

5. LLM returns IncidentReport:
   → HSET job:{job_id} status=persisting stage="Saving report..."
   → PUBLISH job:{job_id}:events {"event":"stage","status":"persisting",...}
   → calls reports-svc POST /reports (saves to SQLite)
   → receives incident_id back

6. Reports-svc confirms save:
   → HSET job:{job_id} status=done incident_id=... latency_ms=6800
   → PUBLISH job:{job_id}:events {"event":"done","incident_id":...,"latency_ms":6800}
   → reports-svc also writes analysis_jobs row to SQLite (durable snapshot)

7. On any error at any stage:
   → HSET job:{job_id} status=failed error="..." latency_ms=...
   → PUBLISH job:{job_id}:events {"event":"failed","error":"...","latency_ms":...}
```

---

## 4. Redis Configuration

| Setting | Value | Rationale |
|---------|-------|-----------|
| `maxmemory-policy` | `allkeys-lru` | Evict least-recently-used keys under memory pressure; job state is ephemeral |
| `appendonly` | `yes` | AOF persistence so jobs survive Redis restart; trades disk for durability |
| `notify-keyspace-events` | `""` (disabled) | Keyspace notifications not needed; orchestrator explicitly publishes events |

---

## 5. Multi-Client SSE Fanout

Multiple frontend clients can watch the same job (e.g. multiple engineers
monitoring the same analysis). Redis pub/sub handles this naturally:

```
Client A → SSE → gateway → SUBSCRIBE job:{job_id}:events
Client B → SSE → gateway → SUBSCRIBE job:{job_id}:events
                                              ↑
                    orchestrator → PUBLISH → channel
                                              ↓
                    Client A receives event
                    Client B receives event
```

The gateway maintains one Redis subscription per SSE client. When the client
disconnects (EventSource closes), the gateway unsubscribes. No fanout logic
in the orchestrator — it publishes once, Redis distributes to all
subscribers.
