# /contracts — Single Source of Truth (SSOT)

> **Role**: This directory is the undisputed Single Source of Truth for every
> microservice, frontend, and infrastructure component in the K8s LLM Incident
> Analyser platform. No application code may be written until the contracts in
> this directory have been reviewed and approved.

---

## 1. Purpose

This directory contains the architectural contracts that define the **what**
and the **how** of inter-service communication, data storage, and runtime
topology — before any line of application code is written.

The contracts-first philosophy ensures:

- **Zero schema drift** — every service speaks the same language because the
  language is defined here, once.
- **Independent buildability** — any service can be implemented by reading
  only the contracts relevant to it.
- **Testable boundaries** — contract tests validate that implementations
  conform to these specs.
- **Frontend-backend alignment** — the Next.js frontend imports TypeScript
  types generated from these contracts, eliminating manual type maintenance.

---

## 2. The Five Pillars

| Pillar | Directory | Format | Status | Purpose |
|--------|-----------|--------|--------|---------|
| **Database** | `database/` | SQL DDL + Redis schema doc | Active | State contracts: table structures, relations, constraints, Redis key patterns |
| **API** | `api/` | OpenAPI 3.1 YAML (7 files) | Active | Synchronous HTTP boundaries: public (gateway) + internal (service-to-service) + SSE event streams |
| **Events** | `events/` | AsyncAPI | Deferred to v2 | v1 uses SSE documented in `api/gateway.yaml`; AsyncAPI added when migrating to Kafka/RabbitMQ |
| **RPC** | `rpc/` | Protobuf (proto3) | Deferred to v2 | v1 uses REST for all internal calls; proto3 added when introducing gRPC |
| **Infrastructure** | `infra/` | Docker Compose + K8s YAML | Active | Runtime topology: ports, env vars, volumes, health checks, RBAC |

### Why RPC and Events are deferred

- **RPC (proto3)**: v1 uses REST (OpenAPI) for all service-to-service
  communication. The overhead of maintaining proto3 specs that aren't used in
  v1 would risk drift. proto3 will be introduced in v2 alongside gRPC for
  high-throughput internal calls (collector → processor → llm). Field names
  will remain snake_case (proto3 native).
- **Events (AsyncAPI)**: v1 uses Redis pub/sub with SSE fanout to the
  frontend. The event payloads are documented in the OpenAPI SSE endpoint
  spec (`api/gateway.yaml`). AsyncAPI will be introduced in v2 if we migrate
  to Kafka or RabbitMQ for event streaming.

---

## 3. Service-to-Contract Map

Each service consumes specific contract files. The table below shows which
files each service must read during implementation:

| Service | Port | API Contract | Database Contract | Infra Contract |
|---------|------|-------------|-------------------|----------------|
| **gateway** | 8000 | `api/gateway.yaml` | — | `infra/docker-compose.yml` |
| **orchestrator** | 8001 | `api/orchestrator.yaml`, `api/gateway.yaml` (SSE events) | `database/redis_schema.md` | `infra/docker-compose.yml` |
| **collector** | 8002 | `api/collector.yaml` | — | `infra/docker-compose.yml`, `infra/k8s/rbac-collector.yaml` |
| **processor** | 8003 | `api/processor.yaml` | — | `infra/docker-compose.yml` |
| **llm** | 8004 | `api/llm.yaml` | — | `infra/docker-compose.yml` |
| **reports** | 8005 | `api/reports.yaml` | `database/schema.sql` | `infra/docker-compose.yml` |
| **scenario** | 8006 | `api/scenario.yaml` | — | `infra/docker-compose.yml`, `infra/k8s/rbac-scenario.yaml` |
| **frontend** | 3000 | `api/gateway.yaml` (generates TS types) | — | `infra/docker-compose.yml` |

---

## 4. Alignment Rules (Strictly Enforced)

These rules are non-negotiable. Any contract file that violates them is a bug
in the contract, not a licence for the implementation to deviate.

### 4.1 Naming Consistency

All field names use **snake_case** across every pillar — database columns,
OpenAPI JSON properties, SSE event payloads, Redis hash fields, and
environment variables.

| Entity | Database | OpenAPI JSON | SSE payload | Redis hash |
|--------|----------|-------------|------------|------------|
| Incident ID | `incident_id` | `incident_id` | `incident_id` | `incident_id` |
| Failure Category | `failure_category` | `failure_category` | `failure_category` | — |
| Created At | `created_at` | `created_at` | `created_at` | `created_at` |

**Frontend exception**: The Next.js frontend may transform snake_case to
camelCase at the fetch boundary using a generated mapper. This is an
implementation concern, not a contract concern. The contract is snake_case.

### 4.2 Type Parity

| SQLite type | OpenAPI type | TypeScript type | Notes |
|------------|-------------|-----------------|-------|
| `TEXT` (UUIDv7) | `string, format: uuid` | `string` | All IDs |
| `TEXT` (enum) | `string, enum: [...]` | `union type` | failure_category, severity, status |
| `TEXT` (free text) | `string` | `string` | summaries, causes, fixes |
| `TEXT` (JSON) | `object` | `record` | `report_json` stored as TEXT, exposed as object in API |
| `REAL` | `number, format: float` | `number` | `confidence` (0.0–1.0) |
| `INTEGER` | `integer, format: int32` | `number` | `latency_ms`, counts |
| `TEXT` (timestamp) | `string, format: date-time` | `string` | ISO 8601 |

### 4.3 Enum Parity

The `failure_category` enum has **exactly 8 values** across all pillars:

```
crash, config, dependency, network, image, resource, probe, unknown
```

The `severity` enum has **exactly 4 values**:

```
low, medium, high, critical
```

The `job_status` enum has **exactly 7 values**:

```
queued, collecting, processing, llm_call, persisting, done, failed
```

Adding or removing a value requires a **major version bump** of the contracts
package and coordinated PRs across all downstream services.

### 4.4 ID Format

All entity IDs are **UUIDv7** strings (time-sortable). Generated using
`uuid_utils.uuid7()` in Python. Stored as `TEXT` in SQLite. Serialised as
`format: uuid` in OpenAPI. Never auto-incrementing integers.

### 4.5 Timestamp Format

All timestamps are **ISO 8601** strings (e.g. `2026-07-21T10:05:33Z`).
Stored as `TEXT` via `datetime('now')` in SQLite. Serialised as
`format: date-time` in OpenAPI. Never Unix epochs in API contracts.

### 4.6 Error Format

All 4xx and 5xx responses across all services use **RFC 7807 Problem Details**:

```json
{
  "type": "https://errors.k8s-llm.io/job-not-found",
  "title": "Job not found",
  "status": 404,
  "detail": "No job exists with job_id 'abc123'",
  "instance": "/api/jobs/abc123"
}
```

### 4.7 Pagination Shape

All list endpoints return the same envelope:

```json
{
  "items": [...],
  "count": 42,
  "limit": 20,
  "offset": 0
}
```

Query parameters: `?limit=20&offset=0`. Default limit: 20. Max limit: 100.

### 4.8 Health Endpoints

Every service exposes `GET /health` returning:

```json
{
  "status": "ok",
  "service": "collector-svc",
  "version": "0.1.0"
}
```

Services with additional state (e.g. llm-svc) may add fields:

```json
{
  "status": "ok",
  "service": "llm-svc",
  "version": "0.1.0",
  "provider": "deepseek",
  "model": "deepseek-chat"
}
```

---

## 5. Versioning

The contracts directory is versioned using **Semantic Versioning**:

| Change type | Version bump | Examples |
|-------------|-------------|----------|
| Breaking | Major (1.0.0 → 2.0.0) | Adding/removing enum value, changing field type, renaming a field, removing an endpoint |
| Additive | Minor (1.0.0 → 1.1.0) | Adding a new endpoint, adding an optional field, adding a new service contract |
| Fix | Patch (1.0.0 → 1.0.1) | Correcting a typo in a description, clarifying a constraint |

Breaking changes require:
1. Major version bump in `contracts/VERSION`
2. PRs in all downstream services to update their pinned contracts version
3. Coordinated deployment (old and new versions are not compatible)

---

## 6. How Services Consume These Contracts

### Python services (gateway, orchestrator, collector, processor, llm, reports, scenario)

This is a **monorepo**: all services live under `services/`. Each service
imports the shared Pydantic models from the local shared package
(`services/shared`, package name `k8s-llm-shared`):

```bash
pip install -e ./services/shared
```

```python
from k8s_llm_shared import IncidentReport, EvidencePackage, AnalysisRequest, JobStatus
```

The Pydantic models in `k8s_llm_shared` are aligned with the OpenAPI schemas
in `api/*.yaml` and the database constraints in `database/schema.sql`. Each
service Dockerfile installs the shared package from the repo at image build
time (no external package registry).

### Next.js frontend

The frontend (`frontend/`) imports TypeScript types generated from the
OpenAPI gateway schema:

```bash
cd frontend
npm run generate:types   # openapi-typescript ../contracts/api/gateway.yaml
```

```typescript
import type { components } from '@/types/api'
type IncidentReport = components['schemas']['incident_report']
```

Type generation uses `openapi-typescript` against `api/gateway.yaml`. The
generated types are checked into `frontend/src/types/api.d.ts` so the
frontend builds without running the generator.

---

## 7. Contract Review Checklist

Before approving contracts, verify:

- [ ] All field names are snake_case across every file
- [ ] All IDs are `format: uuid` in OpenAPI and `TEXT` in SQL
- [ ] All timestamps are `format: date-time` in OpenAPI and `TEXT` in SQL
- [ ] `failure_category` has exactly 8 enum values in SQL CHECK, OpenAPI enum, and TS union
- [ ] `severity` has exactly 4 enum values in SQL CHECK, OpenAPI enum, and TS union
- [ ] `job_status` has exactly 7 enum values in SQL CHECK, OpenAPI enum, and TS union
- [ ] All error responses use RFC 7807 Problem Details schema
- [ ] All list endpoints use the `{items, count, limit, offset}` pagination envelope
- [ ] Every service has `GET /health`
- [ ] No field appears in one pillar with a different name in another pillar
- [ ] No field appears in one pillar with a different type in another pillar
- [ ] docker-compose ports match the OpenAPI `servers` URLs
- [ ] docker-compose env vars match the `.env.example` entries
