# Architecture Overview

> **Reading map**: this is the condensed brief. For the complete,
> teach-yourself-the-whole-system guide see
> [`DEEP-DIVE.md`](./DEEP-DIVE.md); for all docs see
> [`docs/README.md`](./README.md).

## System Purpose

The **K8s LLM Incident Analyser** assists on-call engineers investigating
Kubernetes pod failures. When a pod enters `CrashLoopBackOff`,
`ImagePullBackOff`, or is repeatedly restarted, the platform collects
diagnostic evidence from the cluster, preprocesses and redacts it, sends
it to an LLM with a strict JSON schema, and returns a structured
`IncidentReport` containing the likely root cause, supporting evidence,
and suggested remediation.

The system is a **microservices platform**: seven FastAPI services, Redis,
SQLite, and a Next.js dashboard — defined contract-first in
[`contracts/`](../contracts/README.md), the Single Source of Truth (SSOT)
for every API, schema, and topology decision.

## Topology

```
                 Browser (dashboard)
                   │ REST + SSE
                   ▼
            ┌────────────┐
            │ gateway-svc│ :8000 — public API, CORS, rate limit, SSE proxy
            └───┬───┬───┬┘
     /api/jobs* │   │ /api/reports*, /api/stats   │ /api/scenarios*
                ▼   ▼                             ▼
        ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
        │orchestrator- │──▶│ reports-svc │   │ scenario-svc │
        │svc      :8001│   │        :8005│   │         :8006│
        │              │   │ SQLite (WAL)│   │ kubectl patch│
        │ Redis: jobs, │   └─────────────┘   │ (write RBAC) │
        │ pub/sub, SSE │                     └──────────────┘
        └──┬───┬───┬───┘
  /collect │   │   │ /analyse
           ▼   │   ▼
   ┌───────────┐ │ ┌────────┐
   │collector- │ │ │ llm-svc│ :8004 — providers, prompts, validation
   │svc  :8002 │ │ │  :8004 │        (mock/openai/anthropic/deepseek)
   │kubectl    │ │ └────────┘
   │(read RBAC)│ │
   └───────────┘ │ ┌────────┐
        /process └▶│processor│ :8003 — filter + redact (pure CPU)
                   └────────┘
```

## Service Responsibilities

| Service      | Port | Responsibility                                        | State |
|--------------|------|-------------------------------------------------------|-------|
| gateway      | 8000 | Public API; proxies to internal services; CORS; 60 req/min/IP rate limit; RFC 7807 translation; SSE passthrough | — |
| orchestrator | 8001 | Job lifecycle (7-state machine); coordinates collector→processor→llm→reports over HTTP; publishes SSE events; archives terminal state | Redis |
| collector    | 8002 | Wraps kubectl subprocess (logs, describe, events, restart count, container states); resolves pod by label selector | — |
| processor    | 8003 | Noise/signal log filtering with context windows; secret/PII redaction (7 categories) | — |
| llm          | 8004 | Provider integrations + prompt building + structured-output validation; holds all external API keys | — |
| reports      | 8005 | Owns SQLite (single writer, WAL); reports + job snapshots; dashboard stats | SQLite |
| scenario     | 8006 | Lists/applies/resets fault scenarios via kubectl strategic-merge patch; tracks active scenario (409 on conflict) | in-memory |
| frontend     | 3000 | Next.js 15 dashboard (App Router, Tailwind v4, shadcn/ui) | — |

Internal services are **not** exposed publicly; the frontend only talks to
the gateway. All inter-service calls are REST (contracts/api/*.yaml);
gRPC and message-queue migration are deliberate v2 deferrals.

## The Analysis Lifecycle

Analysis is asynchronous — LLM calls take 2–30s, far too long for a
synchronous request.

```
POST /api/jobs {namespace, pod_name}
  → gateway proxies to orchestrator
  → orchestrator generates job_id (UUIDv7)
  → HSET job:{job_id} status=queued (TTL 24h) + LPUSH job:queue
  → archives snapshot via reports-svc POST /jobs
  → 202 {job_id, status: queued}
  → pipeline runs as a background asyncio task:

    1. status=collecting  → collector-svc  POST /collect   → RawEvidence
    2. status=processing  → processor-svc  POST /process   → EvidencePackage
    3. status=llm_call    → llm-svc        POST /analyse   → IncidentReport
    4. status=persisting  → reports-svc    POST /reports   → incident_id
    5. status=done (incident_id, latency_ms) — archived to SQLite

    Any failure → status=failed (error, latency_ms) — archived too.

GET /api/jobs/{job_id}/stream
  → gateway SSE-proxies orchestrator, which SUBSCRIBEs to the Redis
    channel job:{job_id}:events and forwards each publish as an SSE event
    (stage / done / failed). Current state is replayed first so late
    subscribers see where the job stands. Stream closes on terminal event.
```

The frontend's `/analyse` page renders these events as a live pipeline
timeline and links to the finished report on `done`.

## Data Stores

### Redis (orchestrator-owned)

| Key                  | Type    | Purpose                              | TTL  |
|----------------------|---------|--------------------------------------|------|
| `job:{job_id}`       | Hash    | Job state (status, stage, incident_id, error, latency_ms, timestamps) | 24h |
| `job:queue`          | List    | Job queue (LPUSH; for v2 worker scaling) | — |
| `job:{job_id}:events`| Pub/Sub | SSE event fanout channel             | — |

Config: `appendonly yes`, `maxmemory-policy allkeys-lru`. See
[`contracts/database/redis_schema.md`](../contracts/database/redis_schema.md).

### SQLite (reports-svc-owned, WAL mode)

- `incidents` — one row per report; indexed columns (namespace, pod_name,
  failure_category, severity, confidence, created_at) + `report_json`
  TEXT for the full nested report.
- `analysis_jobs` — durable snapshot of Redis job state, FK-linked to
  `incidents`.

The schema ([`contracts/database/schema.sql`](../contracts/database/schema.sql))
is applied idempotently on startup. Enum CHECK constraints are in exact
parity with the OpenAPI enums and the shared Pydantic models.

## The Pipeline Stages (unchanged semantics from v1)

1. **Collector** — kubectl logs (current + previous, tail=500, timestamps),
   describe pod, namespace events, restart count, container statuses.
   Failed kubectl calls return empty strings, not errors — the pipeline
   degrades gracefully.
2. **Preprocessor** — drops probe/metrics noise, keeps signal lines
   (errors, OOMKilled, CrashLoopBackOff…) with ±3 lines of context,
   deduplicates, caps at 100 lines, truncates pod status to 2000 chars.
3. **Redactor** — masks passwords, API keys (OpenAI/Anthropic/generic),
   DB URLs, auth headers, emails with category tags
   (`[PASSWORD=REDACTED]`, …) before anything leaves the cluster.
4. **LLM** — pluggable providers selected by `LLM_PROVIDER`:
   mock (heuristic, deterministic), openai (`chat.completions.parse`
   structured outputs), anthropic (`messages.parse`), deepseek (JSON
   mode + schema in prompt). All validate against the `IncidentReport`
   Pydantic schema.

## Contracts & Shared Code

- `contracts/` is the SSOT: OpenAPI 3.1 (public + internal), SQL DDL,
  Redis schema, infra topology, alignment rules (snake_case everywhere,
  UUIDv7 IDs, ISO 8601 timestamps, RFC 7807 errors, `{items,count,limit,offset}`
  pagination, `/health` on every service).
- `services/shared` (`k8s-llm-shared`) is the Python expression of the
  contracts — Pydantic models, enums, ProblemDetail, UUIDv7 helpers,
  FastAPI error handlers — installed into every service image from the
  monorepo (no external registry).
- The frontend generates TypeScript types from `contracts/api/gateway.yaml`
  via `openapi-typescript` (checked in at `frontend/src/types/api.d.ts`).

## Kubernetes Deployment

`k8s/services/` deploys the platform into the `analyser` namespace,
isolated from the `demo` namespace where the target workload runs:

- **collector-svc** runs as `collector-sa` with a **read-only ClusterRole**
  (pods, pods/log, events, namespaces — get/list/watch only).
- **scenario-svc** runs as `scenario-sa` with a **Role scoped to the demo
  namespace** (deployments/services/configmaps — get/list/patch/update).
- **reports-svc** is pinned to 1 replica (`Recreate`) with a PVC — SQLite
  is single-writer.
- **gateway** and **frontend** are exposed via NodePort (30080 / 30030).

## Frontend

Next.js 15 App Router, TypeScript strict, Tailwind v4, shadcn/ui. Pages:
dashboard (stats + charts), `/analyse` (live SSE pipeline timeline),
`/jobs`, `/reports` (+ detail), `/scenarios` (apply/reset with confirms).
`NEXT_PUBLIC_API_URL` is inlined at build time and must point at a
browser-reachable gateway address.

## Deliberate v2 Deferrals

- **gRPC/proto3** for internal calls (REST suffices at current throughput)
- **AsyncAPI + Kafka/RabbitMQ** (Redis pub/sub + SSE suffices for fanout)
- **PostgreSQL** (SQLite WAL suffices at ~10 analyses/day)
- **Authentication** (v1 is open with CORS *; add API key/OIDC in v2)
- **Multi-worker job queue** (Redis list already in place for BRPOP scaling)
