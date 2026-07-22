# K8s LLM Incident Analyser

LLM-assisted log analysis for incident response in Kubernetes environments —
built as a **microservices platform** with a Next.js operations dashboard.

When a pod enters `CrashLoopBackOff`, `ImagePullBackOff`, or is repeatedly
restarted, the platform collects diagnostic evidence from the cluster,
preprocesses and redacts it, sends it to an LLM with a strict JSON schema,
and returns a structured `IncidentReport` containing the likely root cause,
supporting evidence, and suggested remediation — streamed live to the
dashboard as the pipeline progresses through its stages.

## Architecture

Seven FastAPI microservices + Redis + SQLite + Next.js frontend, defined
contract-first in [`contracts/`](contracts/README.md) (the Single Source of
Truth: OpenAPI, SQL DDL, Redis schema, infra topology).

```
                 Browser
                   │
                   ▼
            ┌────────────┐
            │  frontend  │ Next.js 15 (App Router, Tailwind, shadcn/ui)  :3000
            └─────┬──────┘
                  │ REST + SSE
                  ▼
            ┌────────────┐
            │ gateway-svc│ public API · CORS · rate limit · SSE proxy    :8000
            └───┬───┬───┬┘
        /api/jobs   │   └─────────────┐
                ▼   ▼                 ▼
        ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
        │orchestrator- │   │ reports-svc │   │ scenario-svc │
        │svc      :8001│   │        :8005│   │         :8006│
        │job machine + │   │ SQLite (WAL)│   │ kubectl patch│
        │SSE pub/sub   │   └─────────────┘   └──────────────┘
        └──┬───┬───┬───┘
           │   │   │
     ▼     ▼   ▼   ▼
  ┌─────┐┌────────┐┌────────┐
  │coll-││process-││ llm-svc│
  │ector││or :8003││  :8004 │
  │:8002│└────────┘└────────┘
  └─────┘
           Redis :6379 — job state hashes + pub/sub event channels
           SQLite      — incidents + analysis_jobs (owned by reports-svc)
```

Analysis is **asynchronous**: `POST /api/jobs` returns `202` with a
`job_id`; the orchestrator runs the pipeline in the background, publishing
stage events (`queued → collecting → processing → llm_call → persisting →
done/failed`) to Redis; the frontend streams them live over SSE.

## Quickstart

### Prerequisites

- Docker + Docker Compose
- A Kubernetes cluster (minikube, kind, or k3s) with `kubectl` configured
- For local dev: Python 3.12+, Node 22+

### Full stack (Docker Compose)

```bash
git clone https://github.com/1hirak/k8s-llm-incident-analyser.git
cd k8s-llm-incident-analyser

# Start everything (mock LLM provider — no API keys needed)
docker compose up --build -d

# Open the dashboard
open http://localhost:3000

# Public API
curl http://localhost:8000/health
```

### Kubernetes (minikube) — platform in-cluster

```bash
minikube start
eval $(minikube docker-env)

# Build all images into minikube's daemon
docker build -t k8s-demo-app:latest ./demo-app
for svc in gateway orchestrator collector processor llm reports scenario; do
  docker build -f services/$svc/Dockerfile -t k8s-llm-$svc-svc:latest .
done
docker build -t k8s-llm-frontend:latest ./frontend

# Deploy the demo workload + the platform
kubectl apply -f k8s/base/
kubectl apply -f k8s/services/

# Dashboard: http://$(minikube ip):30030  ·  Gateway: http://$(minikube ip):30080
```

### Local development (hot reload)

```bash
python3 -m venv .venv && source .venv/bin/activate
make dev                 # installs shared package + all dev deps
make test                # run every test suite

# Full stack with uvicorn --reload + Next.js HMR
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### End-to-end smoke test

```bash
# Requires the compose stack + a reachable cluster with the demo app deployed
make e2e
```

## Configuration

Copy `.env.example` to `.env`. Only the **llm-svc** holds external API keys.

| Variable            | Default         | Description                          |
|---------------------|-----------------|--------------------------------------|
| `LLM_PROVIDER`      | `mock`          | `mock` / `openai` / `anthropic` / `deepseek` |
| `OPENAI_API_KEY`    | —               | Required if provider is `openai`     |
| `ANTHROPIC_API_KEY` | —               | Required if provider is `anthropic`  |
| `DEEPSEEK_API_KEY`  | —               | Required if provider is `deepseek`   |
| `LLM_MODEL`         | provider-specific | Model name override                |
| `LLM_MAX_TOKENS`    | `2000`          | Max tokens for LLM response          |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Gateway URL (inlined at frontend build time) |

## Public API (gateway-svc, :8000)

| Method | Path                                  | Purpose                              |
|--------|---------------------------------------|--------------------------------------|
| GET    | `/health`                             | Liveness + configured LLM provider   |
| POST   | `/api/jobs`                           | Start an analysis job (202 + job_id) |
| GET    | `/api/jobs`                           | List jobs (paginated, filterable)    |
| GET    | `/api/jobs/{job_id}`                  | Job state                            |
| GET    | `/api/jobs/{job_id}/stream`           | SSE stream of stage events           |
| GET    | `/api/reports`                        | List report summaries                |
| GET    | `/api/reports/{incident_id}`          | Full incident report                 |
| GET    | `/api/stats?range=24h\|7d\|30d`       | Dashboard aggregates                 |
| GET    | `/api/scenarios`                      | List fault scenarios                 |
| POST   | `/api/scenarios/{scenario_id}/apply`  | Apply a fault (409 if one active)    |
| POST   | `/api/scenarios/reset`                | Reset cluster to healthy baseline    |

All errors are RFC 7807 Problem Details. Full spec:
[`contracts/api/gateway.yaml`](contracts/api/gateway.yaml).

### Example

```bash
# Start an analysis and watch the stages
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"namespace": "demo", "pod_name": "demo-app"}'
# → {"job_id": "01938a7b-...", "status": "queued"}

curl -N http://localhost:8000/api/jobs/01938a7b-.../stream
# event: stage → collecting → processing → llm_call → persisting
# event: done  → {"incident_id": "01938a7c-...", ...}

curl http://localhost:8000/api/reports/01938a7c-...
```

## Dashboard (frontend, :3000)

| Page          | What it shows                                                   |
|---------------|-----------------------------------------------------------------|
| `/`           | Stats cards, category/latency charts, recent reports            |
| `/analyse`    | Start an analysis; live pipeline timeline over SSE              |
| `/jobs`       | All analysis jobs with status badges and filters                |
| `/reports`    | Paginated, filterable report list                               |
| `/reports/id` | Full report: root cause, evidence, fix, copyable kubectl commands |
| `/scenarios`  | Apply/reset fault scenarios with confirmation dialogs           |

TypeScript types are generated from the OpenAPI contract
(`cd frontend && npm run generate:types`).

## Fault Scenarios

Ten scenarios exercise distinct failure categories (unchanged from v1):

| #  | Scenario        | Category   | Fault                         |
|----|-----------------|------------|-------------------------------|
| 01 | missing-env     | config     | DATABASE_URL removed          |
| 02 | db-unavailable  | dependency | DATABASE_URL points to dead host |
| 03 | crashloop       | crash      | Nonexistent command           |
| 04 | imagepull       | image      | Nonexistent image tag         |
| 05 | oom             | resource   | Memory limit 32Mi             |
| 06 | readiness       | probe      | Bad readiness probe path      |
| 07 | liveness        | probe      | Liveness probe hits /fault/slow |
| 08 | bad-configmap   | config     | Invalid LOG_LEVEL             |
| 09 | app-exception   | crash      | STARTUP_FAULT=crash           |
| 10 | wrong-port      | network    | Service targetPort mismatch   |

Apply via the dashboard, the API, or `scripts/run_scenario.sh 05-oom`.

## Evaluation

The harness runs scenarios against a classifier and scores against ground
truth. It now talks to the running services over HTTP (so the compose
stack must be up, and the cluster must be running each scenario):

```bash
python -m evaluation.harness --classifier llm        # via llm-svc
python -m evaluation.harness --classifier keyword    # local baseline
python -m evaluation.harness --classifier rulebased  # local baseline
python -m evaluation.harness --classifier keyword --scenarios 01-missing-env 05-oom
```

Service URLs default to localhost ports; override with `COLLECTOR_URL`,
`PROCESSOR_URL`, `LLM_URL`.

## Project Structure

```
k8s-llm-incident-analyser/
├── contracts/                # Single Source of Truth (OpenAPI, SQL, Redis, infra)
├── services/
│   ├── shared/               # k8s-llm-shared: Pydantic contract models
│   ├── gateway/              # :8000 public API gateway
│   ├── orchestrator/         # :8001 pipeline coordinator + SSE (Redis)
│   ├── collector/            # :8002 kubectl evidence collector
│   ├── processor/            # :8003 preprocessing + redaction
│   ├── llm/                  # :8004 LLM providers (mock/openai/anthropic/deepseek)
│   ├── reports/              # :8005 SQLite persistence
│   └── scenario/             # :8006 fault scenario management
│   (each with app/, tests/, requirements.txt, Dockerfile)
├── frontend/                 # Next.js 15 dashboard
├── demo-app/                 # Fault-injecting demo workload
├── evaluation/               # Harness (HTTP), baselines, ground truth, metrics
├── k8s/
│   ├── base/                 # Healthy demo-app deployment
│   ├── scenarios/            # 10 fault-injecting strategic merge patches
│   └── services/             # Platform deployment manifests (+ RBAC)
├── tests/                    # Root suites: evaluation, manifests, integration
├── scripts/                  # run_scenario.sh, e2e_smoke.sh
├── docker-compose.yml        # Full 11-container platform stack
├── docker-compose.dev.yml    # Hot-reload dev override
└── Makefile                  # Dev task runner
```

## Testing

```bash
make test            # all suites: 8 service suites + root suite (~560 tests)
make test-services   # per-service pytest suites
make test-root       # root suite (evaluation, k8s manifests, integration)
make lint            # ruff
```

The integration suite (`tests/integration/`) composes the real service
apps in-process — full job lifecycle with no Docker, cluster, or Redis
required. The E2E smoke test (`make e2e`) validates the live stack against
a real cluster.

## Documentation

| Doc | What it is |
|-----|-----------|
| [`docs/DEEP-DIVE.md`](docs/DEEP-DIVE.md) | **Start here** — the complete guide to understanding the whole software: philosophy, architecture, end-to-end traces, every service, frontend, evaluation, testing, ops playbook |
| [`docs/architecture.md`](docs/architecture.md) | Condensed architecture brief |
| [`docs/README.md`](docs/README.md) | Index of all documentation |
| [`contracts/README.md`](contracts/README.md) | The Single Source of Truth: pillars, alignment rules, review checklist |
| [`docs/Technical-Documentation.md`](docs/Technical-Documentation.md) | v1 monolith reference (historical) |
| [`docs/Deep-Dive-05-OOM-Walkthrough.md`](docs/Deep-Dive-05-OOM-Walkthrough.md) | Narrative trace of one OOM scenario |

## License

Research project — see LICENSE file (if present).
