# Deep Dive — Understanding the Whole Software

> **Audience**: anyone who wants to understand *every moving part* of the
> K8s LLM Incident Analyser — how it is structured, why it is built the way
> it is, and where to look when you want to change something.
>
> **Scope**: the current microservices platform (v2). For the historical
> v1 monolith see [`Technical-Documentation.md`](./Technical-Documentation.md);
> for a single-scenario narrative trace see
> [`Deep-Dive-05-OOM-Walkthrough.md`](./Deep-Dive-05-OOM-Walkthrough.md);
> for a condensed architecture brief see [`architecture.md`](./architecture.md).

---

## Table of Contents

1. [How to Use This Document](#1-how-to-use-this-document)
2. [The 60-Second Mental Model](#2-the-60-second-mental-model)
3. [The Problem and the Product](#3-the-problem-and-the-product)
4. [The Contract-First Philosophy (the Key to Everything)](#4-the-contract-first-philosophy-the-key-to-everything)
5. [Architecture Overview](#5-architecture-overview)
6. [The Analysis Lifecycle — A Complete End-to-End Trace](#6-the-analysis-lifecycle--a-complete-end-to-end-trace)
7. [The Domain Model](#7-the-domain-model)
8. [Service Deep Dives](#8-service-deep-dives)
9. [The State Stores: Redis and SQLite](#9-the-state-stores-redis-and-sqlite)
10. [The Frontend](#10-the-frontend)
11. [The Demo Workload and Fault Scenarios](#11-the-demo-workload-and-fault-scenarios)
12. [The Evaluation System](#12-the-evaluation-system)
13. [Testing Strategy](#13-testing-strategy)
14. [Infrastructure and Deployment](#14-infrastructure-and-deployment)
15. [Operational Playbook — "Where Do I Touch?"](#15-operational-playbook--where-do-i-touch)
16. [Quirks, Gotchas, and Known Limitations](#16-quirks-gotchas-and-known-limitations)
17. [Glossary](#17-glossary)
18. [Annotated File Map](#18-annotated-file-map)

---

## 1. How to Use This Document

Pick a reading path:

| Path | Time | Sections | Goal |
|------|------|----------|------|
| **Orientation** | ~20 min | 2, 4, 5, 6 | Understand what the system does and how the pieces talk |
| **Contributor** | ~1 hour | + 7, 8, 15, 16 | Be able to modify any service safely |
| **Full mastery** | ~2–3 hours | everything, plus the source files each section points to | Understand the whole software, end to end |

Two habits will make the codebase read itself:

1. **Always start from `contracts/`.** Every API, table, Redis key, enum
   value, port, and env var is specified there *before* any code. If code
   and contracts disagree, the code is wrong (or the contract needs a
   version bump).
2. **Follow one job through the system.** The entire platform exists to
   move one JSON object — an analysis job — through four pipeline stages.
   Section 6 traces that journey literally, hop by hop.

---

## 2. The 60-Second Mental Model

A pod in your Kubernetes cluster is misbehaving — `CrashLoopBackOff`,
`ImagePullBackOff`, OOM-killed, probe failures. You want to know *why*,
fast, without leaking secrets to an LLM vendor.

You (or the dashboard) call:

```
POST /api/jobs {"namespace": "demo", "pod_name": "demo-app"}
```

The platform then runs an **asynchronous four-stage pipeline**:

```
collector  →  processor  →  llm  →  reports
(kubectl)    (filter+      (LLM     (SQLite)
             redact)       call)
```

- **collector-svc** shells out to `kubectl` and gathers raw evidence:
  current + previous logs, `describe pod`, namespace events, restart
  count, container states.
- **processor-svc** throws away noise (health checks, metrics scrapes),
  keeps error lines with ±3 lines of context, and **masks secrets** so
  nothing sensitive ever reaches an LLM vendor.
- **llm-svc** builds a strict prompt, calls the configured provider
  (mock / OpenAI / Anthropic / DeepSeek), and validates the response
  against a Pydantic schema.
- **reports-svc** persists the resulting `IncidentReport` (root cause,
  category, severity, confidence, evidence, fix, commands) into SQLite.

Because LLM calls take seconds, the API is **async**: `POST /api/jobs`
returns `202` + a `job_id` immediately; an orchestrator advances the job
through 7 states (`queued → collecting → processing → llm_call →
persisting → done/failed`), publishing every transition to Redis pub/sub;
the dashboard watches live over **SSE** (Server-Sent Events).

Everything — every field name, enum value, endpoint, Redis key, SQL
column — is defined once in **`contracts/`**, the Single Source of Truth.

---

## 3. The Problem and the Product

### The problem

On-call engineers debugging Kubernetes pod failures face three
compounding issues:

- **Signal-to-noise collapse** — a failing pod emits hundreds of log
  lines per minute; the one line that explains the failure is buried in
  probe and metrics noise.
- **Cross-resource detective work** — the root cause usually requires
  `kubectl logs`, `kubectl describe pod`, `kubectl get events`, and the
  container's *previous* (crashed) logs stitched together.
- **Knowledge gap under pressure** — at 03:00 you don't need a search
  engine; you need a ranked, evidence-cited answer to "what is wrong and
  what do I do next".

### The product

The K8s LLM Incident Analyser turns a failing pod into a **structured
incident report** in under ~10 seconds:

```json
{
  "incident_id": "01938a7c-…",
  "incident_summary": "Container exceeds its 32Mi memory limit and is OOM-killed on startup.",
  "likely_root_cause": "Memory limit of 32Mi is far below the demo app's ~64Mi working set…",
  "affected_component": "demo-app",
  "failure_category": "resource",
  "severity": "high",
  "confidence": 0.92,
  "supporting_evidence": [ { "source": "pod_status", "pod": "demo-app-…", "evidence": "Last State: Terminated — Reason: OOMKilled" } ],
  "suggested_fix": "Raise the memory limit to at least 128Mi…",
  "recommended_commands": ["kubectl patch deployment demo-app -n demo --type json -p '…'"],
  "human_verification_steps": ["Confirm the new limit with kubectl describe pod…"],
  "created_at": "2026-07-21T10:05:39Z"
}
```

It is also a **research artefact**: a built-in evaluation harness replays
ten canonical fault scenarios and scores the LLM against two hand-written
baseline classifiers (keyword and rule-based) to answer the dissertation
question — *does an LLM beat classical classifiers at failure-category
accuracy and root-cause identification?*

### What the platform is made of

| Layer | Pieces |
|-------|--------|
| **Contracts** | `contracts/` — OpenAPI 3.1 ×7, SQL DDL, Redis schema, infra topology |
| **Backend** | 7 FastAPI microservices + 1 shared Pydantic package |
| **State** | Redis 7 (job state + pub/sub) · SQLite WAL (reports + job snapshots) |
| **Frontend** | Next.js 15 dashboard (React 19, Tailwind v4, shadcn/ui) |
| **Target workload** | `demo-app` — a fault-injectable FastAPI app + 10 kubectl patch scenarios |
| **Research** | `evaluation/` — harness, 2 baselines, ground truth, metrics |
| **Ops** | Docker Compose (prod + dev override), K8s manifests + RBAC, Makefile, GitHub Actions CI |

---

## 4. The Contract-First Philosophy (the Key to Everything)

Most repos grow code first and document later. This one inverts it:
**`contracts/` is the undisputed Single Source of Truth (SSOT)**, written
before application code, and everything else is a *projection* of it.

### The five pillars

| Pillar | Location | Status | Defines |
|--------|----------|--------|---------|
| **API** | `contracts/api/*.yaml` (7 OpenAPI 3.1 files) | Active | Every HTTP boundary — public gateway API + internal service-to-service APIs + SSE event schemas |
| **Database** | `contracts/database/schema.sql`, `redis_schema.md` | Active | SQLite DDL (tables, CHECK constraints, triggers, indexes) and Redis key patterns/TTLs/channels |
| **Infrastructure** | `contracts/infra/` (compose files, k8s namespace/RBAC, `.env.example`) | Active | Runtime topology: ports, env vars, volumes, health checks |
| **Events** | `contracts/events/README.md` | Deferred to v2 | v1 uses SSE documented inside `api/gateway.yaml`; AsyncAPI arrives with Kafka/RabbitMQ |
| **RPC** | `contracts/rpc/README.md` | Deferred to v2 | v1 uses REST internally; proto3 arrives with gRPC |

`contracts/VERSION` (`1.0.0`) is semantically versioned: adding an enum
value is a **breaking (major)** change requiring coordinated PRs in every
service.

### The alignment rules (§4 of `contracts/README.md`)

These are the invariants that let you read any payload anywhere in the
system and immediately understand it:

- **snake_case everywhere** — DB columns, JSON fields, SSE payloads,
  Redis hash fields, env vars. No exceptions.
- **UUIDv7 IDs** — time-sortable, generated by `uuid_utils.uuid7()`,
  stored as `TEXT`, serialised as `format: uuid`. Never auto-increment.
- **ISO 8601 timestamps** — `2026-07-21T10:05:33Z` strings, never epochs.
- **RFC 7807 errors** — every 4xx/5xx from every service is a Problem
  Details JSON object with `type`/`title`/`status`/`detail`/`instance`,
  served as `application/problem+json`.
- **Pagination envelope** — every list endpoint returns
  `{items, count, limit, offset}`; `?limit=20&offset=0`, max limit 100.
- **`GET /health` on every service** — `{status, service, version}` plus
  optional extras (llm-svc adds `provider`/`model`; collector/scenario
  add `cluster`).
- **Enum parity** — `failure_category` has *exactly 8* values,
  `severity` *exactly 4*, `job_status` *exactly 7*, identical across SQL
  CHECK constraints, OpenAPI enums, Pydantic `Literal`s, and the
  generated TypeScript unions. Tests enforce this (`TestSchemaSqlParity`).

### How code expresses the contracts

```
contracts/api/*.yaml  ──┬──►  services/shared (k8s_llm_shared)  ──► imported by all 7 Python services
                        │      Pydantic models, enums, ProblemDetail,
                        │      UUIDv7 helpers, FastAPI error handlers
                        └──►  frontend/src/types/api.d.ts  ──► generated by openapi-typescript,
                               checked into git               consumed by the Next.js app
```

`k8s-llm-shared` (version 1.0.0) is a small pip package in the monorepo
(`pip install -e ./services/shared`). Its modules:

| Module | Contents |
|--------|----------|
| `enums.py` | `FailureCategory` (8), `Severity` (4), `JobStatus` (7), `EvidenceSource` (4), `ProviderId` (4) — all `typing.Literal` unions |
| `models.py` | ~20 Pydantic models: `IncidentReport`, `EvidenceItem`, `RawEvidence`, `EvidencePackage`, `AnalysisRequest`, `JobCreated`, `JobState`, SSE events, scenario/stats/health models, reports-svc internal models |
| `errors.py` | `ProblemDetail` (RFC 7807) with an `of()` factory that builds `https://errors.k8s-llm.io/<slug>` type URLs |
| `ids.py` | `new_id()` (UUIDv7) and `utc_now_iso()` (ISO 8601 `Z`) — the *only* ways IDs/timestamps are minted |
| `web.py` | `add_error_handlers(app)` — installs exception handlers that turn HTTP errors, request validation errors, and unhandled exceptions into RFC 7807 responses; `health_payload()` builder |

Every service's `main.py` starts with the same two lines of ceremony:
create the `FastAPI(...)` app, then `add_error_handlers(app)`. That is
why error responses look identical everywhere.

**Why this matters to you as a reader**: if you're unsure what a payload
looks like, don't read three services — read one model in
`services/shared/src/k8s_llm_shared/models.py` or one OpenAPI file.

---

## 5. Architecture Overview

### 5.1 Topology

```
                        Browser (dashboard, dark UI)
                          │ REST + SSE
                          ▼
                  ┌───────────────┐
                  │  frontend     │  Next.js 15 · :3000 · NodePort 30030
                  └───────┬───────┘
                          │  (only public hop besides NodePorts)
                          ▼
                  ┌───────────────┐
                  │  gateway-svc  │  :8000 · NodePort 30080
                  │ auth + CORS   │  60 req/min/IP sliding-window rate limit
                  │  SSE proxy    │  RFC 7807 translation
                  └──┬────┬────┬──┘
        /api/jobs*   │    │    │  /api/reports* · /api/stats   /api/scenarios*
                     ▼    │    ▼                                 ▼
            ┌─────────────┐│  ┌─────────────┐         ┌──────────────────┐
            │orchestrator ││  │ reports-svc │         │  scenario-svc    │
            │-svc   :8001 ││  │       :8005 │         │          :8006   │
            │ job FSM     ││  │ SQLite WAL  │         │ kubectl patch    │
            │ SSE pub/sub │──► │ single      │         │ (write RBAC in   │
            │ pipeline    │  │ writer      │         │  demo namespace) │
            └──┬───┬───┬──┘  └─────────────┘         └──────────────────┘
   POST /collect │   │   │ POST /analyse
                 ▼   │   ▼
        ┌──────────┐ │ ┌──────────┐
        │collector-│ │ │ llm-svc  │ :8004 — mock/openai/anthropic/deepseek
        │svc :8002 │ │ │  :8004   │        holds ALL external API keys
        │ kubectl  │ │ └──────────┘
        │ (read    │ │ ┌──────────┐
        │  RBAC)   │ └►│processor-│ :8003 — noise filter + secret redaction
        └──────────┘   │svc :8003 │        (pure CPU, stateless)
                       └──────────┘

   Redis :6379  — job state hashes (24h TTL) + job:queue list + pub/sub channels
   SQLite       — incidents + analysis_jobs (owned exclusively by reports-svc)
```

**Nine FastAPI services + shared package + Redis + SQLite + Next.js
frontend.** Two more compose services (`demo-app`, `db` = PostgreSQL 16)
are the *target workload*, not platform infrastructure.

### 5.2 The three communication planes

Understanding the system is easiest when you separate its three kinds of
traffic:

| Plane | Technology | Used for | Why chosen |
|-------|-----------|----------|------------|
| **Request plane** | Synchronous REST (OpenAPI-specified) | All service-to-service calls: gateway→orchestrator/reports/scenario/remediation, watcher→orchestrator, orchestrator→collector/processor/llm/reports | Simple, debuggable, contract-specified; LLM latency (~6s) dwarfs HTTP overhead |
| **Event plane** | Redis pub/sub → SSE | Job stage transitions fanned out to browsers | Sub-ms fanout to N clients; no broker needed at this scale |
| **State plane** | Redis hashes (hot) + SQLite WAL (durable) | Job state (24h TTL) and report/job history | Redis = fast reads + pub/sub; SQLite = queryable history, single writer |

### 5.3 Service responsibility matrix

| Service | Port | Owns | Never does | State |
|---------|------|------|-----------|-------|
| gateway | 8000 | Public API surface, deployment-configured auth/CORS, rate limit, SSE passthrough | Business logic; it only proxies | — |
| orchestrator | 8001 | Job lifecycle (7-state machine), pipeline coordination, SSE publishing, job archival | Touch SQLite directly; parse logs; call LLMs | Redis |
| collector | 8002 | `kubectl` subprocess calls; pod-name→label resolution | Filtering/redaction (that's processor) | — |
| processor | 8003 | Noise/signal log filtering, context windows, PII/secret redaction | Cluster access; LLM calls | — |
| llm | 8004 | Provider SDKs, prompt building, output validation; **all API keys** | Persistence; cluster access | — |
| reports | 8005 | SQLite (single writer), reports, job snapshots, stats | Redis; LLM calls | SQLite |
| scenario | 8006 | Fault scenario list/apply/reset via `kubectl patch` | Analysis (it breaks things; it doesn't diagnose them) | in-memory active-scenario lock |
| watcher | 8007 | Read-only unhealthy-pod scan; deduplicated job submission | Mutate cluster resources or run remediation | Redis cooldown keys |
| remediation | 8008 | Typed server-side dry-run and explicit approved Deployment changes | Execute free-form LLM commands | Redis proposals |
| frontend | 3000 | Dashboard UX, SSE consumption, type-safe API client | Talk to internal services — gateway only | — |

### 5.4 Trust boundaries and security model

- **Only the gateway is public.** Internal services bind to the Docker
  network / ClusterIP; the frontend *only* knows the gateway URL.
- **Only llm-svc holds LLM API keys.** `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
  / `DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY` are injected into exactly one container. The
  redactor exists so that *evidence* secrets (DB URLs, tokens in logs)
  never leave the cluster either.
- **Kubernetes RBAC is split deliberately** (see §14): collector and watcher
  are read-only; scenario is limited to demo-only fault injection; remediation
  uses a separate namespace-scoped identity for typed Deployment patches.
- **Authentication is deployment-configured.** Development can be open, while
  external-cluster Compose requires a gateway Bearer token and restricted CORS;
  ingress TLS/OIDC remains a production hardening recommendation.
- **Rate limiting** at the gateway: 60 requests/minute per IP over a
  sliding 60s window, in-memory (per-replica; a distributed limiter is
  v2). `/health` and CORS preflight are exempt.
- **Every error is RFC 7807** — including 429s and upstream 502s.

### 5.5 Key design decisions and their trade-offs

| Decision | Alternative rejected | Why | Cost |
|----------|---------------------|-----|------|
| Async job API (`202` + SSE) | Synchronous request | LLM calls take 2–30s; browsers/proxies time out | Client must handle a stream; more moving parts (Redis pub/sub) |
| REST everywhere internally | gRPC/proto3 | ~10 analyses/day; velocity > wire efficiency | Verbose JSON over HTTP (fine at this scale) — deferred to v2 |
| Redis for job state | Postgres/SQLite only | Needs pub/sub for SSE + sub-ms reads for polling | A second datastore to operate |
| SQLite WAL single writer | PostgreSQL | Zero-ops at dissertation scale; reports-svc is the only writer | 1-replica pin (`Recreate`), no horizontal scale — deferred to v2 |
| `kubectl` subprocess | Python K8s client library | Behavioural parity with what operators run; trivially testable via `subprocess.run` mocks | Requires kubectl binary + kubeconfig/RBAC in the container |
| Contracts-first monorepo | Per-service schemas | Zero schema drift; frontend types generated, not hand-written | Contract changes need coordination (by design) |
| In-process background task for jobs | Celery/RQ workers | v1 runs ~10 jobs/day; `asyncio.create_task` suffices | Jobs die if orchestrator restarts mid-flight (state remains in Redis; no resume) |
| `job:queue` Redis list exists but is unused | Remove it | It's the v2 seam: swap inline execution for `BRPOP` workers with no contract change | Slight "why is this here?" confusion (now you know) |

---

## 6. The Analysis Lifecycle — A Complete End-to-End Trace

This is the single most important section for understanding the system.
Follow one job, `job_id = 01938a7b-…`, from click to report.

### Step 0 — the user starts an analysis

Dashboard `/analyse` page (or curl):

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"namespace": "demo", "pod_name": "demo-app"}'
```

### Step 1 — gateway (:8000) proxies

- `RateLimitMiddleware` slides the caller's IP window; under 60 req/min →
  pass.
- `POST /api/jobs` → `proxy_request()` forwards method, query params,
  body, and content-type to `orchestrator:8001/jobs` with a 60s timeout.
- Upstream unreachable/timeout → gateway itself emits `502` Problem
  Details. Any upstream problem+json body is passed through untouched.

### Step 2 — orchestrator (:8001) creates the job

`POST /jobs` (`create_job`):

1. `job_id = new_id()` (UUIDv7).
2. `JobStore.create()` → `HSET job:{job_id}` `{status: queued, namespace,
   pod_name, created_at, updated_at}` + `EXPIRE 86400` + `LPUSH
   job:queue {job_id}`.
3. Best-effort archival: `POST reports-svc/jobs` (a durable `queued`
   snapshot in SQLite). If reports-svc is down the job still proceeds —
   archival failure never fails a job.
4. `asyncio.create_task(_run_with_timeout())` starts the pipeline in the
   background, wrapped in `asyncio.wait_for(..., PIPELINE_TIMEOUT=120s)`.
5. Returns **202** `{"job_id": "01938a7b-…", "status": "queued"}`.

Meanwhile the browser opens `EventSource(/api/jobs/01938a7b-…/stream)`.
The gateway SSE-proxies it (a dedicated no-read-timeout httpx client) to
the orchestrator, which **replays current state first** (so late joiners
know where the job stands) and then `SUBSCRIBE`s to Redis channel
`job:01938a7b-…:events`.

### Step 3 — pipeline stage 1: collecting

`Pipeline.run()`:

- `store.transition(job_id, "collecting", "Collecting evidence for demo/demo-app")`
  → `HSET` status/stage/updated_at → `PUBLISH` a `stage` SSE event.
- `POST collector:8002/collect {"namespace":"demo","pod_name":"demo-app"}`
  (60s timeout).
- collector-svc runs `kubectl` (30s per-call timeout):
  - Pod resolution: exact-name lookup; if missing, label selector
    `app=demo-app` → first matching pod name.
  - `logs --tail=500 --timestamps` (current container)
  - `logs --tail=500 --timestamps --previous` (crashed container)
  - `describe pod`
  - `get events --sort-by=.metadata.creationTimestamp`
  - jsonpath restartCount; jsonpath `.status.containerStatuses` (parsed JSON)
  - **Graceful degradation**: any failed call yields `""`/`0`/`[]`, not an
    error — the pipeline continues with partial evidence.
- Returns `RawEvidence` (7 fields). Can be large — hundreds of KB.

### Step 4 — pipeline stage 2: processing

- `store.transition(..., "processing", "Filtering logs and redacting secrets")`.
- `POST processor:8003/process` with the RawEvidence (30s timeout).
- processor-svc (pure CPU, stateless):
  1. **Preprocess**: drop noise lines (`GET /health`, `/ready`,
     `/metrics`, blank); find signal lines (regex catalogue: `error`,
     `exception`, `traceback`, `OOMKilled`, `CrashLoopBackOff`,
     `ImagePullBackOff`, `connection refused`, …); keep each signal line
     **±3 lines of context**; deduplicate; cap at 100 lines per log
     stream; filter events to `Warning`/signal lines; truncate pod status
     to 2000 chars.
  2. **Redact**: 7 regex categories → `[PASSWORD=REDACTED]`,
     `[API_KEY=REDACTED]`, `[ANTHROPIC_KEY=REDACTED]`,
     `[OPENAI_KEY=REDACTED]`, `[DB_URL=REDACTED]`,
     `[AUTH_HEADER=REDACTED]`, `[EMAIL=REDACTED]`.
- Returns `EvidencePackage` — small enough for an LLM context window and
  safe to send to a vendor.

### Step 5 — pipeline stage 3: llm_call

- The orchestrator asks llm-svc `GET /health` for a human stage label:
  `"Calling deepseek deepseek-chat"` → `store.transition(..., "llm_call", label)`.
- `POST llm:8004/analyse` with the EvidencePackage (60s timeout).
- llm-svc:
  1. `get_provider()` reads `LLM_PROVIDER` (unknown values fall back to
     `mock` with a warning).
  2. `build_prompt()` renders the system prompt (analyst persona + 5
     anti-hallucination rules) and a user prompt containing all evidence
     sections + the full `IncidentReport` JSON schema.
  3. The provider calls its API (see §8.6 for the per-provider matrix).
  4. Output is validated into a Pydantic `IncidentReport` — schema
     violations become 500 Problem Details, never bad data downstream.

### Step 6 — pipeline stage 4: persisting

- `store.transition(..., "persisting", "Saving report")`.
- `POST reports:8005/reports` `{report, namespace, pod_name, job_id}`
  (30s timeout) → reports-svc inserts the `incidents` row (indexed
  columns + full `report_json`) **and** links
  `analysis_jobs.incident_id` → returns `201 {"incident_id": …}`.

### Step 7 — done

- `store.complete(job_id, incident_id, latency_ms, report)` → `HSET`
  terminal fields → `PUBLISH` the `done` event:
  ```json
  {"event":"done","job_id":"01938a7b-…","status":"done",
   "incident_id":"01938a7c-…","failure_category":"resource",
   "severity":"high","latency_ms":6800}
  ```
- Final archival `POST reports-svc/jobs` with status `done`.
- Every SSE subscriber receives the event; orchestrator closes the
  stream; the dashboard renders a link to `/reports/01938a7c-…`.

**Failure path**: any exception at any stage →
`store.fail(job_id, error[:500], latency)` → `failed` event → archived as
`failed`. Timeout of the whole pipeline (>120s) → failed with
"Pipeline exceeded 120s".

### Timeline summary

| t≈ | Hop | Technology |
|----|-----|-----------|
| 0 ms | browser → gateway → orchestrator, `202` | REST |
| +10 ms | job hash in Redis, snapshot row in SQLite | Redis HSET · HTTP POST |
| +50 ms | stage event `collecting` on every SSE client | Redis PUBLISH → SSE |
| +800 ms | collector returns `RawEvidence` | kubectl subprocess ×7 |
| +850 ms | stage `processing`; processor returns `EvidencePackage` | regex CPU work |
| +900 ms | stage `llm_call: Calling deepseek deepseek-chat` | REST |
| +6.5 s | llm-svc returns validated `IncidentReport` | vendor API |
| +6.6 s | stage `persisting`; row inserted; `done` published | SQLite WAL · SSE |
| **~7 s total** | report retrievable at `GET /api/reports/{incident_id}` | REST |

---

## 7. The Domain Model

All models live in `services/shared/src/k8s_llm_shared/models.py`.
Field names are snake_case by contract; IDs are UUIDv7; timestamps are
ISO 8601 strings.

### Enums (exact parity across SQL / OpenAPI / Pydantic / TypeScript)

```python
FailureCategory = "crash" | "config" | "dependency" | "network"
                | "image" | "resource" | "probe" | "unknown"        # 8
Severity        = "low" | "medium" | "high" | "critical"             # 4
JobStatus       = "queued" | "collecting" | "processing" | "llm_call"
                | "persisting" | "done" | "failed"                   # 7
EvidenceSource  = "pod_log" | "previous_pod_log"
                | "kubernetes_event" | "pod_status"                  # 4
ProviderId      = "mock" | "openai" | "anthropic" | "deepseek" | "openrouter" # 5
```

### The canonical output: `IncidentReport`

| Field | Type | Constraints | Meaning |
|-------|------|-------------|---------|
| `incident_id` | UUIDv7 str | default factory | Server-side identity (also SQLite PK) |
| `incident_summary` | str | ≥10 chars | One-paragraph "what happened" |
| `likely_root_cause` | str | ≥10 chars | The diagnosis |
| `affected_component` | str | — | Usually the pod/deployment name |
| `failure_category` | enum(8) | — | Machine-classifiable bucket (drives charts + evaluation) |
| `severity` | enum(4) | — | Triage priority |
| `confidence` | float | 0.0–1.0 | LLM self-assessment; prompt rules demand lower values on ambiguity |
| `supporting_evidence` | list[`EvidenceItem`] | ≥1 item | Cited proof — every claim must trace to collected evidence |
| `suggested_fix` | str | — | Human-executable guidance; never auto-applied |
| `recommended_commands` | list[str] | — | kubectl guidance; never executed by the platform |
| `recommended_actions` | list[`RemediationAction`] | optional | Typed proposals may be dry-run and require explicit approval |
| `human_verification_steps` | list[str] | — | Checklist to confirm the fix worked |
| `created_at` | ISO str | default factory | Generation time |

`EvidenceItem` = `{source: EvidenceSource, pod: str, timestamp?: str,
evidence: str}`. Extra JSON keys from LLMs are ignored
(`model_config = {"extra": "ignore"}`) — forward compatibility.

### Pipeline-internal models (never in the public API)

| Model | Producer → Consumer | Fields |
|-------|--------------------|--------|
| `RawEvidence` | collector → processor | `namespace`, `pod_name`, `current_logs`, `previous_logs`, `pod_status`, `k8s_events`, `restart_count`, `container_states: list[Any]` |
| `EvidencePackage` | processor → llm | `namespace`, `pod_name`, `current_logs`, `previous_logs`, `pod_status_summary`, `k8s_events_filtered`, `restart_count` (all filtered + redacted) |
| `AnalysisRequest` | client → gateway/orchestrator | `namespace` (default `"demo"`), `pod_name` |

### Job models

- `JobCreated` = `{job_id, status}` — the 202 response.
- `JobState` = the full job record with **triple parity**: it is exactly
  the Redis hash `job:{job_id}`, exactly the `analysis_jobs` row, and
  exactly the `GET /api/jobs/{id}` response:
  `{job_id, namespace, pod_name, status, stage?, incident_id?,
  latency_ms?, error?, created_at, updated_at}`.

### SSE payloads (`GET /api/jobs/{job_id}/stream`)

Three named events, all snake_case JSON:

| `event:` | Model | Payload |
|----------|-------|---------|
| `stage` | `SseStageEvent` | `{event, job_id, status, stage, updated_at}` |
| `done` | `SseDoneEvent` | `{event, job_id, status, incident_id, failure_category, severity, latency_ms}` |
| `failed` | `SseFailedEvent` | `{event, job_id, status, error, latency_ms}` |

### Other shared models

`ReportSummary` (list view of a report — no nested arrays), `StatsResponse`
+ `LatencyPoint` (dashboard aggregates), `ScenarioSummary` /
`ScenarioApplyResponse`, `SaveReportRequest`/`SaveJobRequest` (reports-svc
internal writes), `ProviderInfo` (llm-svc `/providers`), `HealthResponse`,
`ProblemDetail`.

---

## 8. Service Deep Dives

Each subsection: what it does, its endpoints, how the code is laid out,
its configuration, and its failure behaviour. Services share a skeleton:
`app/main.py` (FastAPI surface) + domain modules + `tests/` +
`requirements.txt` + `Dockerfile` (python:3.12-slim, repo-root build
context, `pip install /shared` first).

### 8.1 `services/shared` — the contract in Python

Not a service — a pip package (`k8s-llm-shared==1.0.0`, deps: `pydantic`,
`uuid-utils`). Contents covered in §4 and §7. Key insight: **business
logic never redefines shapes**; every service imports them. The shared
test suite (83 tests) includes contract-parity tests that fail if enum
literals drift from `schema.sql`.

### 8.2 gateway-svc (:8000) — the public front door

**Files**: `app/main.py` (routes), `app/proxy.py` (forwarding),
`app/rate_limit.py` (middleware).

**Endpoints** (all proxy to an upstream):

| Public route | Upstream | Notes |
|--------------|----------|-------|
| `GET /health` | llm + collector `/health` | Aggregates `provider` and `cluster` into its own health (2s timeouts, tolerant of failure) |
| `POST/GET /api/jobs`, `GET /api/jobs/{id}` | orchestrator | generic proxy, 60s timeout |
| `GET /api/jobs/{id}/stream` | orchestrator | **SSE proxy**: dedicated `httpx.AsyncClient(timeout=None)`, byte-stream passthrough, `X-Accel-Buffering: no` |
| `GET /api/reports`, `GET /api/reports/{id}`, `GET /api/stats` | reports | generic proxy |
| `GET /api/scenarios`, `POST /api/scenarios/{id}/apply`, `POST /api/scenarios/reset` | scenario | generic proxy |

How the proxy works: forwards method + query params + raw body +
content-type; strips nothing except hop-by-hop headers; on
`httpx.TimeoutException`/`HTTPError` returns its own `502` Problem
Details; otherwise passes the upstream status and body through verbatim
(upstream problem+json survives intact).

Rate limiter: `BaseHTTPMiddleware`, per-IP `deque` of timestamps over a
60s sliding window, default 60/min (`RATE_LIMIT_PER_MINUTE`), 429 Problem
Details when exceeded. In-memory → per-replica (fine at 1 replica).

**Env**: `ORCHESTRATOR_URL`, `REPORTS_URL`, `SCENARIO_URL`, `LLM_URL`,
`COLLECTOR_URL`, `RATE_LIMIT_PER_MINUTE`.

### 8.3 orchestrator-svc (:8001) — the state machine

**Files**: `app/main.py` (API + SSE), `app/pipeline.py` (stage
coordination), `app/store.py` (Redis access).

**Endpoints**:

| Route | Behaviour |
|-------|-----------|
| `POST /jobs` | 202 + `JobCreated`; kicks off background pipeline (see §6) |
| `GET /jobs` | Paginated list from Redis (SCAN `job:*`, regex-filtered to UUID keys so `job:queue` is excluded), sorted by `created_at` desc, optional `?status=` filter |
| `GET /jobs/{id}` | Single `JobState` or 404 Problem |
| `GET /jobs/{id}/stream` | SSE: replay current state (terminal → single `done`/`failed` event and close), then forward pub/sub messages; disconnect-aware; closes on terminal event |
| `GET /health` | standard |

**`JobStore`** implements `contracts/database/redis_schema.md` exactly:
hash per job with 24h TTL, `job:queue` LPUSH on create, `PUBLISH` on
every transition via typed SSE models. Terminal writes (`complete`,
`fail`) truncate errors to 500 chars.

**`Pipeline`** is deliberately boring: four typed HTTP calls with
per-stage timeouts (collect 60s / process 30s / analyse 60s / reports
30s), each wrapped so failures raise `RuntimeError("<stage>-svc …")` —
which is why job error messages tell you *which* stage died. The llm
stage label is fetched from llm-svc `/health` so the UI can say "Calling
deepseek deepseek-chat". Archival to reports-svc is best-effort at
creation, done, and failed.

**Env**: `REDIS_URL`, `COLLECTOR_URL`, `PROCESSOR_URL`, `LLM_URL`,
`REPORTS_URL`, `PIPELINE_TIMEOUT` (default 120s).

### 8.4 collector-svc (:8002) — the kubectl wrapper

**Files**: `app/collector.py` (`KubernetesCollector`), `app/main.py`.

Single endpoint `POST /collect` (plus `/health`, which reports
`cluster: connected|unreachable` via `kubectl version --client=false`
with a 5s probe).

`KubernetesCollector` details worth knowing:

- Every call goes through `_run(*args)` → `subprocess.run(capture_output,
  text=True, timeout=30, check=False)`; non-zero exit logs stderr
  (truncated to 200 chars) and still returns stdout; timeout returns `""`.
- **Pod resolution**: `_pod_exists()` (jsonpath `.metadata.name`,
  `--ignore-not-found`); if absent, `find_pod_by_label(namespace,
  "app=<pod_name>")` — this is why you can pass `"demo-app"` instead of
  `"demo-app-7d9f8b6c5-x2abc"`.
- Log flags: `--tail=500 --timestamps=true`, plus `--previous` for the
  crashed container's logs (crucial for CrashLoopBackOff diagnosis).
- `container_states` is parsed JSON from jsonpath
  `{.status.containerStatuses}` — survives as `list[Any]` in
  `RawEvidence` but is **not** forwarded by the processor (the describe
  text carries the useful bits).
- Missing kubectl binary → 500 Problem "kubectl binary not found in
  container".

**Env**: `KUBECTL_TIMEOUT` (default 30s). Note: `KUBECTL_LOG_TAIL`
appears in compose/k8s manifests but is currently **unused** by the code
(tail is a function default) — see §16.

### 8.5 processor-svc (:8003) — noise filter + redactor

**Files**: `app/preprocessor.py`, `app/redactor.py`, `app/main.py`.
Endpoint: `POST /process` (RawEvidence → EvidencePackage).

The **preprocessor** algorithm (`_filter_with_context`):

1. Split lines. A line is **signal** if it matches the signal catalogue
   (three compiled regexes: generic errors —
   `error|exception|traceback|fatal|critical|failed|refused|timeout`
   case-insensitive; K8s states — `OOMKilled|CrashLoopBackOff|
   ImagePullBackOff|BackOff|Unhealthy`; config hints — `missing|not
   found|permission denied|address already in use`).
2. A signal line is dropped anyway if it's also **noise** (`GET /health`,
   `GET /ready`, `GET /metrics`, blank) — noise wins ties.
3. Every surviving index keeps `i-3 … i+3` (context window, default 3).
4. Deduplicate by stripped content, preserve order, cap at
   `MAX_LOG_LINES` (100).
5. Events: keep lines containing `Warning` or matching signal.
6. `pod_status_summary = pod_status[:2000]`.

The **redactor** applies 7 ordered regex substitutions to all four text
fields (see §6 step 4 for the tag list). Order matters: `sk-ant-…` is
matched before generic `sk-…` so Anthropic keys get the more specific
tag.

**Env**: `MAX_LOG_LINES` (100), `CONTEXT_WINDOW` (3). Pure CPU — no I/O,
no state, trivially cacheable/parallelisable in future.

### 8.6 llm-svc (:8004) — providers, prompts, validation

**Files**: `app/main.py`, `app/prompts.py`, `app/validator.py`,
`app/llm/{base,__init__,mock,openai,anthropic,deepseek}_provider.py`.

**Endpoints**:

| Route | Behaviour |
|-------|-----------|
| `POST /analyse` | EvidencePackage → validated `IncidentReport` (or 500 Problem) |
| `GET /providers` | Lists all 4 providers with `available: bool` (API key present?) and effective model |
| `GET /health` | Adds `provider` + `model` to the standard payload |

**Prompt engineering** (`prompts.py`): the system prompt fixes the
persona ("Kubernetes incident analyst") and five rules — only use
provided evidence, don't invent log lines, lower confidence on
ambiguity, never recommend automated remediation, respond with JSON
only. The user prompt lays out six labelled sections (pod status,
current logs, previous logs, events, restart count) with
`"(no … available)"` fallbacks, then embeds the **full
`IncidentReport.model_json_schema()`** so the model sees the exact
target shape.

**Provider matrix**:

| Provider | Mechanism | Structured-output strategy | Notable error handling |
|----------|-----------|---------------------------|------------------------|
| `mock` | Heuristic if/elif over evidence text (DATABASE_URL→config, connection refused→dependency, oomkilled→resource, imagepull→image, probes→probe, ContainerCannotRun→crash, …) | Constructs `IncidentReport` directly; confidence 0.5 | Deterministic; used in all tests and default deployments |
| `openai` | `openai.AsyncOpenAI` | `chat.completions.parse(response_format=IncidentReport)` — server-side structured outputs | `LengthFinishReasonError` → "increase LLM_MAX_TOKENS"; `ContentFilterFinishReasonError` → clear message; refusal/`parsed=None` → ValueError |
| `anthropic` | `anthropic.AsyncAnthropic` | `messages.parse(output_format=IncidentReport)` | Missing parsed output → ValueError with raw text logged |
| `deepseek` | raw `httpx` POST to `api.deepseek.com` (OpenAI-compatible) | `response_format={"type":"json_object"}` + schema & example appended to system prompt | Non-JSON/truncated → RuntimeError; then `IncidentReport.model_validate` |

Default models: `gpt-4o-mini`, `claude-haiku-4-5-20251001`,
`deepseek-chat`. `LLM_MODEL` overrides; `LLM_MAX_TOKENS` (2000) is shared.
Providers are imported eagerly (a missing SDK surfaces at boot, not
mid-request) but instantiated per call — so only the selected provider
needs its key. Unknown `LLM_PROVIDER` → warn + fall back to mock.

`ReportValidator` is the schema gatekeeper used by tests and available to
providers: `validate(dict|str)` → `IncidentReport`,
rejecting bad JSON, non-objects, and schema violations.

### 8.7 reports-svc (:8005) — the system of record

**Files**: `app/db.py` (`ReportsDB`), `app/main.py`. Sole owner of
SQLite; applies `contracts/database/schema.sql` idempotently on startup
(`executescript` of `SCHEMA_PATH`, defaulting to the repo file in dev).

**Endpoints**:

| Route | Behaviour |
|-------|-----------|
| `POST /reports` | 201; inserts `incidents` row (indexed columns + `report_json`) **and** links `analysis_jobs.incident_id` in the same transaction |
| `GET /reports` | Paginated summaries; filters `namespace`, `pod_name`, `category`, `severity`; ordered `created_at DESC` |
| `GET /reports/{id}` | Full report (the stored `report_json`, parsed) or 404 |
| `POST /jobs` | 201; UPSERT job snapshot (`ON CONFLICT(job_id)` — COALESCE preserves `incident_id`/`latency_ms` once set) |
| `GET /jobs` | Paginated job history from SQLite (the durable twin of orchestrator's Redis list) |
| `GET /stats?range=24h\|7d\|30d` | Dashboard aggregates (regex-validated range) |
| `GET /health` | standard |

Implementation notes: one connection guarded by a `threading.Lock`
(single writer discipline), `row_factory=Row`; SQLite `datetime('now')`
values are converted to ISO 8601 `Z` at the boundary (`_to_iso8601`).
Stats: `total_reports`, `reports_24h`, mean latency of `done` jobs in
range, mean confidence in range, `category_counts` (all time), and the
last 50 latency points (chronological).

**Env**: `DATABASE_PATH` (`./data/reports.db` local, `/data/reports.db`
in Docker), `SCHEMA_PATH` (set to `/app/schema.sql` in the image).

### 8.8 scenario-svc (:8006) — controlled chaos

**Files**: `app/scenarios.py` (`ScenarioManager`), `app/main.py`.

**Endpoints**:

| Route | Behaviour |
|-------|-----------|
| `GET /scenarios` | Lists `k8s/scenarios/*/fault.yaml` dirs; enriches each with `description`, `true_failure_category`, `true_severity` from `evaluation/ground_truth/{id}.json` |
| `POST /scenarios/{id}/apply` | 404 if unknown id · **409 if another scenario is active** · 503 if cluster unreachable · applies the patch |
| `POST /scenarios/reset` | Deletes the demo deployment, re-applies `k8s/base/` (namespace, configmap, deployment, service), waits for rollout (120s) |
| `GET /health` | Adds `cluster: connected|unreachable` |

Apply mechanics: read `fault.yaml`, extract `(kind, metadata.name)` with a
line scanner (no YAML dependency — same approach as
`scripts/run_scenario.sh`), then
`kubectl patch <kind>/<name> -n demo --type strategic -p <patch>`.
The **active-scenario lock is in-memory** (`self._active`) — one fault at
a time per replica, and the lock is lost on restart (see §16).

**Env**: `K8S_NAMESPACE` (demo), `SCENARIOS_DIR`, `BASE_DIR`,
`GROUND_TRUTH_DIR` (mounted read-only in compose).

---

## 9. The State Stores: Redis and SQLite

### Redis (owned by orchestrator-svc)

| Key | Type | TTL | Contents |
|-----|------|-----|----------|
| `job:{job_id}` | Hash | 24h | Full `JobState` field set |
| `job:queue` | List | — | LPUSHed job_ids (v2 worker seam; always empty in v1) |
| `job:{job_id}:events` | Pub/Sub channel | ephemeral | JSON SSE payloads |

Server config: `appendonly yes` (AOF durability), `maxmemory-policy
allkeys-lru` (job state is expendable), keyspace notifications off.
Why 24h TTL: active jobs get sub-ms reads; completed jobs are archived to
SQLite; the TTL lets the UI poll a just-finished job without hitting the
DB while preventing unbounded growth. Multi-client SSE fanout is free:
N subscribers per channel, the orchestrator publishes once.

### SQLite (owned by reports-svc, WAL mode)

Two tables (full DDL with comments in `contracts/database/schema.sql`):

- **`incidents`** — one row per report. Indexed filter columns
  (`namespace,pod_name`, `failure_category`, `created_at DESC`), enum
  CHECK constraints in exact parity with the contracts, `confidence`
  range CHECK, denormalised summary fields for fast list views, and
  `report_json TEXT` holding the complete nested report (evidence,
  commands, verification steps — deliberately not normalised; they're
  always read with the report, never queried independently).
- **`analysis_jobs`** — durable job snapshot: PK `job_id`, 7-value status
  CHECK, nullable `stage`/`incident_id`/`latency_ms`/`error`, and
  `incident_id` as FK → `incidents`.

Triggers `trg_incidents_updated` / `trg_jobs_updated` auto-maintain
`updated_at`. No seed data; no migration framework (CREATE IF NOT EXISTS
on startup — schema evolution is a v2 concern).

**Reading tip**: Redis is the *hot* truth for in-flight jobs (and what
`GET /api/jobs*` serves); SQLite is the *cold* truth for history, stats,
and anything older than 24h.

---

## 10. The Frontend

Next.js 15.3 (App Router) · React 19 · TypeScript strict · Tailwind v4
(CSS-first, no config file) · shadcn/ui (new-york style, Radix
primitives) · recharts · sonner. Forced dark theme (Linear-inspired:
`#050506` canvas, indigo `#5E6AD2` accent, Inter font).

### Pages (all under `frontend/src/app/`)

| Route | Type | Data | Highlights |
|-------|------|------|-----------|
| `/` | server | `getStats("7d")` + `listReports(limit:6)` | Stat cards, category bar chart, latency line chart, recent reports; `ErrorState`/`EmptyState` branches |
| `/analyse` | client | `createJob` → `streamJob` (SSE) | The only SSE page: phase machine `idle→running→done/failed`, live `PipelineTimeline`, result card linking to the report |
| `/jobs` | client | `listJobs` | Status filter (all 7), refresh, skeletons, offset pagination (15/page) |
| `/reports` | client | `listReports` | Draft/applied filter pattern (namespace, pod, category, severity), shared `ReportsTable` |
| `/reports/[id]` | server | `getReport` | Async params (Next 15), 404 → `notFound()`; tabs: Evidence / Commands (copy buttons + "review before running") / Verification; `ConfidenceMeter` |
| `/scenarios` | client | `listScenarios`, `applyScenario`, `resetScenarios` | Confirmation dialogs (unclosable while in-flight), sonner toasts incl. 409→warning; only page using toasts |
| `layout.tsx` | server | — | `<html class="dark">`, ambient background layers, `AppSidebar` + `MobileNav`, global `Toaster` |
| `loading.tsx` ×2, `not-found.tsx` | server | — | Route-level suspense skeletons; 404 page. There is deliberately no `error.tsx` — errors are handled inline per page |

### Data layer (`src/lib/`)

- **`api.ts`** — the only gateway client. Dual URL split:
  server components use `INTERNAL_API_URL` (default `http://gateway:8000`,
  cluster-internal), browser code uses `NEXT_PUBLIC_API_URL` (default
  `http://localhost:8000`, **inlined at build time**). All GETs are
  `cache: "no-store"` (always dynamic). `ApiError` carries the RFC 7807
  `problem` body.
- **`sse.ts`** — wraps `EventSource` on `/api/jobs/{id}/stream` with
  named listeners; auto-closes on `done`/`failed`; returns an
  unsubscribe used on unmount.
- **`utils.ts`** — `cn()` plus deliberately UTC-deterministic formatters
  (`formatDateTime`, `formatLatency`, `formatPercent`, `shortId`) so
  server HTML and client hydration never disagree.
- **`logger.ts`** — tiny structured console logger; `middleware.ts` logs
  every request as JSON; `instrumentation.ts` registers process-level
  `uncaughtException`/`unhandledRejection` handlers.

### Types

`src/types/api.d.ts` is **generated** by `openapi-typescript` from
`contracts/api/gateway.yaml` (`npm run generate:types`) and checked in —
the frontend can never drift from the contract; CI regenerates and builds
it. `src/types/index.ts` re-exports the generated unions/models and adds
hand-written envelopes (`Paginated<T>`, list responses, `StatsRange`).

### Components worth knowing

`app-sidebar` (nav + `HealthPill` polling `/health` every 30s with a
red/amber/emerald dot), `pipeline-timeline` (6-step vertical stepper with
live stage text), `reports-table`, `evidence-card` (per-source colours),
`confidence-meter` (colour thresholds 80/60), `status-badge` (per-enum
colours), `category-chart` + `latency-chart` (recharts themed via CSS
vars), `spotlight-card` (mouse-tracked glow with zero re-renders),
`stat-card`, `copy-button`, `empty-state`, `error-state` (default retry =
`router.refresh()`), plus 14 shadcn primitives in `ui/` (restyled
`card.tsx`, `progress.tsx` with custom indicator prop).

### Docker

Multi-stage `node:22-alpine`: `dev` (compose dev target) → `deps` →
`builder` (`ARG NEXT_PUBLIC_API_URL` inlined into the bundle at build) →
`runner` (`output: "standalone"`, non-root `nextjs` user, `node
server.js`, `INTERNAL_API_URL` as a runtime env).

---

## 11. The Demo Workload and Fault Scenarios

### demo-app (`demo-app/`)

A 62-line FastAPI target workload with deliberate failure modes:

- **Startup gates** (lifespan): `STARTUP_FAULT=crash` → raise
  `RuntimeError`; missing `DATABASE_URL` → raise `RuntimeError` (this is
  how scenarios 09 and 01 kill it before serving).
- Endpoints: `/health`, `/ready` (fails when `DATABASE_URL` contains
  "unavailable" — scenario 02), `/fault/crash` (ZeroDivisionError),
  `/fault/oom` (allocates 600 × 1MiB — trips scenario 05's 32Mi limit),
  `/fault/slow` (sleeps 30s — trips scenario 07's liveness timeout).
- Base deployment (`k8s/base/`): namespace `demo`, ConfigMap
  `demo-config`, 1-replica Deployment (64Mi/128Mi memory req/limits,
  readiness `/ready`, liveness `/health`), Service port 8000.

### The ten fault scenarios (`k8s/scenarios/*/fault.yaml`)

Each is a **strategic merge patch** applied by scenario-svc:

| # | ID | Category | Severity | Fault mechanism |
|---|----|----------|----------|-----------------|
| 01 | missing-env | config | critical | `DATABASE_URL` set to empty |
| 02 | db-unavailable | dependency | high | `DATABASE_URL` points at an unreachable host |
| 03 | crashloop | crash | critical | Command replaced with `/bin/nonexistent` |
| 04 | imagepull | image | critical | Image tag set to a nonexistent tag |
| 05 | oom | resource | high | Memory limit dropped to 32Mi |
| 06 | readiness | probe | medium | Readiness probe path broken |
| 07 | liveness | probe | high | Liveness probe pointed at `/fault/slow` |
| 08 | bad-configmap | config | medium | ConfigMap `LOG_LEVEL=INVALID` |
| 09 | app-exception | crash | high | `STARTUP_FAULT=crash` env injected |
| 10 | wrong-port | network | medium | Service `targetPort` mismatched (9999) |

Ground truth for scoring lives in `evaluation/ground_truth/{id}.json`
(fields: `scenario_id`, `description`, `true_root_cause`,
`true_affected_component`, `true_failure_category`, `true_severity`,
`expected_log_patterns`, `expected_event_reasons`,
`correct_remediation_keywords`, `notes`). Scenarios 08 and 10 are the
*subtle* ones — pod-level evidence barely shows them, which is exactly
where LLM reasoning is tested against baselines.

Apply from the dashboard, the API, or `scripts/run_scenario.sh 05-oom`
(which also supports `all` and `reset`).

---

## 12. The Evaluation System

Purpose: answer the research question — *does a structured-output LLM
beat classical classifiers on failure-category accuracy and root-cause
identification across the ten scenarios?*

### Harness (`evaluation/harness.py` + `services.py`)

Dependency-injected design (`Collector`/`Preprocessor`/`Redactor`
Protocols) so the whole flow is testable without a cluster. In production
mode the injected implementations are HTTP adapters calling the live
services (`ServiceCollector` → collector:8002, `ServicePreprocessor` →
processor:8003, `ServiceLLMProvider` → llm:8004; `PassThroughRedactor`
because redaction happens inside processor-svc).

Flow per scenario: `collect → process → redact → classify → evaluate`,
timed with `time.monotonic()`. **Important**: the harness does *not*
apply faults itself — you apply a scenario (dashboard/API/script), then
run the harness against the currently-broken deployment.

CLI:

```bash
python -m evaluation.harness --classifier llm        # via llm-svc (default)
python -m evaluation.harness --classifier keyword    # local baseline
python -m evaluation.harness --classifier rulebased  # local baseline
python -m evaluation.harness --classifier keyword --scenarios 01-missing-env 05-oom \
    --namespace demo --pod-name demo-app --output evaluation/results_keyword.json
```

### Baseline classifiers (`evaluation/baselines/`)

- **Keyword** (`keyword.py`): 7 categories × weighted keyword maps.
  Tier 3 = definitive K8s signals (`oomkilled`, `imagepullbackoff`,
  `environment variable`…), tier 2 = strong, tier 1 = generic symptoms.
  Substring-sum scoring, then **disambiguation**: symptom categories
  (probe) are halved when a root-cause category scores ≥2. Confidence =
  `min(0.9, best/(best+second+0.5))`; `classify_detailed` returns matched
  keywords for explainability.
- **Rule-based** (`rulebased.py`): a priority chain —
  **image > resource > config > dependency > probe > crash > network** —
  first triggered rule wins. Rules parse `Reason:` and Last-State fields
  from describe text (e.g. OOMKilled, ContainerCannotRun, exit code 137),
  plus log/event regexes. Confidence = `min(0.85, 0.5 + 0.1×triggered)`;
  `explain()` returns matched rule + evidence signals.

`classify_with_baseline` adapts either classifier into a report-shaped
dict using lookup tables (`_BASELINE_ROOT_CAUSES/_FIXES/_COMMANDS`).

### Metrics (`evaluation/metrics.py`)

Per scenario, `evaluate(report, ground_truth, latency)` produces:

- `category_correct` — exact match vs `true_failure_category`.
- `root_cause_correct` — word-overlap heuristic (words >4 chars,
  case-insensitive) against `true_root_cause`.
- `schema_valid` — the report re-validates against the Pydantic schema.
- `remediation_keywords_hit` — count of `correct_remediation_keywords`
  found in fix/commands/verification text.
- Plus latency, confidence, evidence count.

`aggregate()` → `{n, category_accuracy, root_cause_accuracy,
schema_valid_rate, mean_latency_s, mean_confidence, mean_evidence_count,
mean_remediation_keywords_hit}`. Caveat: `precision`/`recall` are
fractions of correct over evaluated (no TP/FP/FN confusion matrix), so
F1 equals accuracy — a known simplification.

Results are written to `evaluation/results_{classifier}.json`.

---

## 13. Testing Strategy

**564 test functions** across 9 suites (grep `def test_` count; many are
heavily parametrized, so the executed case count is higher):

| Suite | Tests | Focus |
|-------|-------|-------|
| `services/shared` | 83 | Contract parity: models, enums↔schema.sql, ID/timestamp formats, RFC 7807, web helpers |
| `services/gateway` | 26 | Proxy behaviour, SSE passthrough (byte-exact), 429s, CORS, `parse_problem` edge cases |
| `services/orchestrator` | 28 | Job store (TTL, queue, pub/sub), pipeline stage order, per-stage failure injection, timeout, best-effort archival, SSE replay + live fanout |
| `services/collector` | 63 | kubectl arg construction, graceful degradation, pod resolution, connectivity probe |
| `services/processor` | 65 | Context windows, dedup, caps, every redaction pattern incl. false-positive guards |
| `services/llm` | 82 | Provider matrix (SDKs mocked), prompt content, validator edge cases, `/providers` availability |
| `services/reports` | 37 | Real SQLite: round-trips, filters, upsert semantics, stats, CHECK constraints, triggers |
| `services/scenario` | 30 | Listing/enrichment, apply/reset kubectl calls, 409/503/404 mapping, patch-target parsing |
| `tests/` (root) | 150 | **Integration**: full pipeline composed in-process; **unit**: baselines vs all 10 fixtures, harness, metrics, demo app, K8s manifest validation, contract-drift (RBAC byte-equality with `contracts/infra/k8s/`) |

Techniques worth stealing:

- **Module isolation**: every service's package is named `app`; tests
  load them by scrubbing `sys.modules`/`sys.path` so multiple services
  coexist in one pytest process.
- **In-process composition** (`tests/integration/test_pipeline.py`): a
  `RouterTransport` routes httpx calls by hostname to per-service
  `ASGITransport`s; `fakeredis` stands in for Redis; `subprocess.run` is
  patched with canned kubectl output per scenario. The *entire platform*
  runs a full job lifecycle — all 10 scenarios — with no Docker, cluster,
  Redis, or network.
- **Real SQLite, tmp files** for reports-svc (no DB mocking).
- **`httpx.MockTransport` handlers** that emulate all upstreams for
  gateway/orchestrator tests.
- **Contract-drift guards**: enum literals must appear verbatim in
  `schema.sql`; RBAC/namespace manifests must byte-match the SSOT copies.

Run them: `make test` (all), `make test-services`, `make test-root`,
`make test-cov`, `make lint` (ruff, line-length 100, `E501` ignored).
Every service has an identical `pytest.ini` (`asyncio_mode=auto`).

---

## 14. Infrastructure and Deployment

### Docker Compose (the reference topology)

`docker-compose.yml` runs **13 containers** on one bridge network
(`analyser-net`): the 9 services + frontend + Redis + demo-app +
PostgreSQL. Notable wiring:

- Every service has a `urllib`-based healthcheck; `depends_on:
  service_healthy` chains boot order (Redis → pipeline services →
  orchestrator → gateway → frontend).
- collector, watcher, scenario, and remediation use `kubectl`. The local demo
  uses the generated minikube kubeconfig; external Compose mounts distinct,
  read-only least-privilege kubeconfigs for collector/watcher and remediation.
- scenario additionally mounts `./k8s` and `./evaluation` read-only
  (patches + ground truth).
- reports mounts `./data:/data` (SQLite lives on the host); Redis has a
  named volume with `--appendonly yes --maxmemory-policy allkeys-lru`.
- The root file is kept in sync with `contracts/infra/docker-compose.yml`
  (only relative paths differ).

`docker-compose.dev.yml` (use via `make up-dev`): bind-mounts each
service's `app/` and runs `uvicorn --reload`; frontend runs the `dev`
image target with Next.js HMR; `LOG_LEVEL=DEBUG`.

### Kubernetes (`k8s/`)

Two namespaces, deliberately isolated:

- **`demo`** — the target workload (`k8s/base/`) + fault patches
  (`k8s/scenarios/`).
- **`analyser`** — the platform (`k8s/services/`): one Deployment +
  ClusterIP Service per microservice, Redis, frontend + gateway exposed
  as **NodePorts 30030 / 30080**.

RBAC (the security centrepiece):

| ServiceAccount | Scope | Verbs | Resources |
|----------------|-------|-------|-----------|
| `collector-sa` / `watcher-sa` | read-only Role/ClusterRole | `get, list, watch` | pods, pods/log, events, namespaces |
| `remediation-sa` | target-namespace Role | `get, list, patch` | deployments and rollout reads |
| `scenario-sa` | Role, `demo` namespace only | `get, list, patch, update` | deployments, services, configmaps |

reports-svc is pinned to **1 replica with `Recreate`** strategy + PVC
(SQLite single-writer discipline). All images are built locally
(`imagePullPolicy: IfNotPresent`) — see README's minikube flow.

### Service Dockerfiles

Identical pattern across the 9 services (`python:3.12-slim`, repo-root
build context): `COPY services/shared /shared && pip install /shared`,
then service `requirements.txt`, then `COPY services/<svc>/app ./app`,
`CMD uvicorn app.main:app --host 0.0.0.0 --port <port>`. The shared
package is installed from the monorepo — **no external registry**, so
images always match the contracts in the same commit.

### CI (GitHub Actions)

- **`ci.yml`** — 9-leg matrix (Python 3.12 × {8 service suites + root});
  ruff lint on the root leg; `LLM_PROVIDER=mock` for tests. Separate
  `frontend` job: Node 22, `npm ci`, regenerate types from contracts,
  lint, build.
- **`docker.yml`** — builds all 9 images (buildx, GHA cache); on pushes
  to `main`, publishes 8 platform images to `ghcr.io/<repo>/*:latest`.

### Scripts and Makefile

`scripts/run_scenario.sh` (apply/reset/all faults with rollout waits),
`scripts/e2e_smoke.sh` (8-step live-stack verification: health → list →
reset → apply 05-oom → job 202 → SSE → report category → stats, with
trap-based cleanup). The Makefile wraps everything: `install`, `dev`,
`test*`, `lint`, `format`, `up`, `up-dev`, `down`, `logs`, `build`,
`e2e`, `eval ARGS=…`, `run-scenario SCENARIO=05-oom`, `frontend-*`.

---

## 15. Operational Playbook — "Where Do I Touch?"

| I want to… | Touch | Notes |
|-----------|-------|-------|
| **Add/change an API field** | `contracts/api/*.yaml` → `services/shared/.../models.py` → service code → regenerate frontend types (`make frontend-types`) → bump `contracts/VERSION` if breaking | The contract changes *first*; tests will catch drift |
| **Add an enum value** (e.g. a 9th category) | All pillars: schema.sql CHECKs, OpenAPI enums, `enums.py`, ground truth, baselines, frontend colours | Breaking change — major version bump, coordinated PRs |
| **Add an LLM provider** | New `app/llm/<name>_provider.py` implementing `BaseLLMProvider.analyse`, register in `app/llm/__init__.py:_PROVIDERS`, add key env to compose/`.env.example`/`_PROVIDER_KEY_ENVS`, update `ProviderId` enum (contract change!) | Tests: mirror `test_llm_providers.py` patterns |
| **Add a fault scenario** | `k8s/scenarios/11-…/fault.yaml` + `evaluation/ground_truth/11-….json` + `SCENARIOS` in harness + fixtures/tests | No service code changes needed — listing is filesystem-driven |
| **Change redaction rules** | `services/processor/app/redactor.py` only | Ordered regexes; keep specific patterns before generic |
| **Change log filtering** | `services/processor/app/preprocessor.py` (`NOISE/SIGNAL_PATTERNS`, window, caps via env) | Env-tunable: `MAX_LOG_LINES`, `CONTEXT_WINDOW` |
| **Debug a stuck job** | `redis-cli HGETALL job:{id}` → stage/error; `GET /api/jobs/{id}`; orchestrator logs (`pipeline_failed`); each stage's 500 Problem tells you which svc died | Job TTL 24h; durable copy in `analysis_jobs` |
| **Swap SQLite → Postgres** | `services/reports/app/db.py` + schema contract | Only reports-svc knows SQL — the seam is clean by design |
| **Scale job processing (v2)** | Workers `BRPOP job:queue` instead of inline `asyncio.create_task` | The queue already exists for exactly this |
| **Run the research evaluation** | Apply scenario → `make eval ARGS="--classifier llm"` (or keyword/rulebased) → compare `evaluation/results_*.json` | Harness needs the compose stack + cluster |

---

## 16. Quirks, Gotchas, and Known Limitations

Deliberate v1 trade-offs (documented in contracts as v2 deferrals) plus
things that surprise first-time readers:

1. **No OIDC or ingress TLS** — external Compose requires a gateway Bearer
   token and restricted CORS, but production SSO and transport termination
   still need an ingress or API gateway.
2. **Jobs don't survive an orchestrator restart mid-flight** — the
   background `asyncio` task dies; Redis retains the last state (stuck at
   a non-terminal status until the 24h TTL). No resume logic in v1.
3. **`job:queue` is always empty** — intentional v2 seam (see §5.5).
4. **Rate limiter is per-replica in-memory** — fine at one gateway
   replica; needs Redis backing to scale.
5. **Scenario active-lock is in-memory** — a scenario-svc restart forgets
   which fault is applied (the cluster remains faulted; use
   `POST /api/scenarios/reset`). Multi-replica scenario-svc would also
   break the lock.
6. **`KUBECTL_LOG_TAIL` is declared but unused** — manifests set it, but
   the collector reads only `KUBECTL_TIMEOUT`; tail is hardcoded to 500
   via a function default. Minor contract drift to fix (either wire it up
   or drop it from manifests).
7. **Container states are collected but not forwarded** — processor keeps
   only the describe-text summary; the structured `container_states`
   JSON stops at the collector boundary.
8. **Evaluation `precision`/`recall`/`f1` collapse to accuracy** — no
   confusion matrix in v1 metrics.
9. **Scenario 08/10 score as "unknown" with the mock provider** — by
   design: their evidence isn't visible at pod level, so integration
   tests expect `unknown` there. Real LLMs can reason about them — that's
   the research point.
10. **reports/ at repo root are v1 leftovers** — the v1 monolith wrote
    JSON report files there; v2 stores everything in SQLite
    (`data/reports.db`). The old files are kept as historical evaluation
    artefacts.
11. **Redis `SCAN` listing is O(n)** over job keys — bounded by the 24h
    TTL and dissertation scale (~10 jobs/day).
12. **docs/index.html + Technical-Documentation.md describe the v1
    monolith** — kept as historical reference; this document and
    `architecture.md` describe the current system.

---

## 17. Glossary

| Term | Meaning |
|------|---------|
| **SSOT** | Single Source of Truth — `contracts/`; every schema decision lives there exactly once |
| **Contract-first** | No application code before its contract is reviewed; implementations are projections of contracts |
| **Enum parity** | The exact same enum values in SQL CHECKs, OpenAPI, Pydantic Literals, and TS unions |
| **Job** | One asynchronous analysis run; 7-state lifecycle; lives in Redis (24h) and SQLite (forever) |
| **Stage event** | Redis pub/sub message → SSE frame telling clients the job changed state |
| **RawEvidence** | Collector's unfiltered kubectl output bundle (internal only) |
| **EvidencePackage** | Filtered + redacted evidence; the only thing an LLM ever sees |
| **IncidentReport** | The canonical structured diagnosis; validated Pydantic schema; stored as JSON in SQLite |
| **Problem Details** | RFC 7807 error JSON (`application/problem+json`) used by every service |
| **Scenario** | A kubectl strategic-merge patch that injects a known fault into the demo workload |
| **Ground truth** | Per-scenario JSON with the expected category/root cause/remediation for scoring |
| **Baseline** | Non-LLM classifier (weighted keyword / priority rule-based) used as research comparison |
| **UUIDv7** | Time-sortable UUID; all entity IDs; makes list endpoints chronologically ordered by default |
| **WAL** | SQLite Write-Ahead Logging — concurrent reads during the single writer's transactions |
| **SSE** | Server-Sent Events — one-way browser stream (`EventSource`) used for live pipeline progress |
| **Strategic merge patch** | kubectl's default patch strategy for built-in resources; how faults are injected |

---

## 18. Annotated File Map

```
k8s-llm-incident-analyser/
├── contracts/                     # ★ SSOT — read this first, always
│   ├── VERSION                    # 1.0.0 (semver for all pillars)
│   ├── README.md                  # pillars, alignment rules, review checklist
│   ├── api/                       # OpenAPI 3.1: gateway (public) + 6 internal
│   ├── database/
│   │   ├── schema.sql             # incidents + analysis_jobs DDL, CHECKs, triggers
│   │   └── redis_schema.md        # key patterns, TTLs, pub/sub channels, lifecycle
│   ├── events/README.md           # AsyncAPI — deferred to v2 (why + migration plan)
│   ├── rpc/README.md              # proto3/gRPC — deferred to v2 (why + mapping rules)
│   └── infra/                     # compose SSOT, k8s namespace/RBAC SSOT, .env.example
│
├── services/
│   ├── shared/                    # k8s-llm-shared==1.0.0 — the contracts in Python
│   │   └── src/k8s_llm_shared/    # enums · models · errors · ids · web
│   ├── gateway/        (:8000)    # public API: proxy.py · rate_limit.py · main.py
│   ├── orchestrator/   (:8001)    # main.py (API+SSE) · pipeline.py (stages) · store.py (Redis)
│   ├── collector/      (:8002)    # collector.py (kubectl wrapper) · main.py
│   ├── processor/      (:8003)    # preprocessor.py (noise/signal) · redactor.py (7 patterns)
│   ├── llm/            (:8004)    # prompts.py · validator.py · llm/{base,mock,openai,anthropic,deepseek}
│   ├── reports/        (:8005)    # db.py (SQLite layer) · main.py (reports/jobs/stats)
│   └── scenario/       (:8006)    # scenarios.py (patch apply/reset) · main.py
│       (each service: app/ + tests/ + requirements.txt + Dockerfile)
│
├── frontend/                      # Next.js 15 dashboard
│   ├── src/app/                   # / analyse jobs reports reports/[id] scenarios + layout
│   ├── src/components/            # 14 feature components + ui/ (14 shadcn primitives)
│   ├── src/lib/                   # api.ts (gateway client) · sse.ts (EventSource) · utils/logger
│   ├── src/types/                 # api.d.ts (generated from contracts) · index.ts (envelopes)
│   └── Dockerfile                 # 4-stage: dev → deps → builder (NEXT_PUBLIC_* inlined) → runner
│
├── demo-app/                      # fault-injectable FastAPI target workload
├── evaluation/
│   ├── harness.py                 # DI orchestration: collect→process→redact→classify→score
│   ├── services.py                # HTTP adapters to the live stack
│   ├── metrics.py                 # evaluate() + aggregate()
│   ├── baselines/                 # keyword.py (weighted tiers) · rulebased.py (priority chain)
│   └── ground_truth/              # 10 JSON files — the expected answers
│
├── k8s/
│   ├── base/                      # healthy demo-app: namespace, configmap, deployment, service
│   ├── scenarios/                 # 10 fault-injecting strategic merge patches
│   └── services/                  # platform manifests: 7 svc + redis + frontend, RBAC, NodePorts
│
├── tests/
│   ├── integration/               # full pipeline in-process (RouterTransport + fakeredis)
│   ├── fixtures/                  # per-scenario EvidencePackage factories
│   └── unit/                      # baselines, harness, metrics, demo app, manifest & drift guards
│
├── scripts/                       # run_scenario.sh · e2e_smoke.sh
├── docker-compose.yml             # 13-container full stack
├── docker-compose.dev.yml         # hot-reload override
├── Makefile                       # every dev task
├── pyproject.toml                 # pytest + ruff config (root suite)
├── requirements*.txt              # root (evaluation) + dev deps
├── docs/                          # you are here
│   ├── DEEP-DIVE.md               # ← this document (whole-software guide)
│   ├── architecture.md            # condensed architecture brief
│   ├── Technical-Documentation.md # v1 monolith reference (historical)
│   ├── Deep-Dive-05-OOM-Walkthrough.md  # single-scenario narrative trace
│   ├── index.html                 # rendered v1 docs (historical)
│   └── report_schema.json         # IncidentReport JSON schema snapshot
└── reports/                       # v1 JSON report artefacts (historical; v2 uses SQLite)
```

---

*Last verified against the codebase on 2026-07-22. If code and this
document disagree, trust the code — then fix the document (or the
contract).*
