# RPC Contracts — Deferred to v2

> **Status**: Deferred. v1 uses REST (OpenAPI) for all internal
> service-to-service communication. proto3 / gRPC will be introduced in v2.

---

## Why proto3 is not used in v1

v1 prioritises development velocity and operational simplicity over
internal communication performance. The service-to-service calls are:

- Low frequency (~10 analyses/day at dissertation scale)
- High latency dominated by the LLM call (~6 seconds), not network overhead
- Simple request/response (no streaming, no bidirectional channels)

The overhead of maintaining proto3 specifications, generating stubs in
Python, and running a gRPC server alongside FastAPI in every service is
not justified at this scale.

## What v1 uses instead

All internal service-to-service communication uses **REST over HTTP**,
specified in the OpenAPI 3.1 contracts:

| Service pair | Contract file | Endpoint |
|-------------|---------------|----------|
| orchestrator → collector | `api/collector.yaml` | `POST /collect` |
| orchestrator → processor | `api/processor.yaml` | `POST /process` |
| orchestrator → llm | `api/llm.yaml` | `POST /analyse` |
| orchestrator → reports | `api/reports.yaml` | `POST /reports`, `GET /reports` |
| orchestrator → scenario | `api/scenario.yaml` | `GET /scenarios`, `POST /scenarios/{id}/apply` |
| gateway → orchestrator | `api/orchestrator.yaml` | `POST /jobs`, `GET /jobs/{id}` |

## When proto3 will be introduced

gRPC will be added in v2 if any of the following occur:

- Internal call frequency increases (batch evaluation, multi-pod analysis)
- Network overhead becomes measurable relative to LLM latency
- Need for bidirectional streaming between orchestrator and LLM-svc
- Migration to a polyglot backend (Go/Rust services alongside Python)

## v2 proto3 Mapping Rules (Reference)

When proto3 is introduced, the following type mappings will be used to
maintain parity with the database and API contracts:

| SQLite type | OpenAPI type | proto3 type | Notes |
|------------|-------------|------------|-------|
| `TEXT` (UUID) | `string, format: uuid` | `string` | All IDs |
| `TEXT` (enum) | `string, enum: [...]` | `enum` | failure_category, severity, status |
| `TEXT` (free text) | `string` | `string` | Summaries, causes |
| `REAL` | `number, format: float` | `double` | confidence |
| `INTEGER` | `integer, format: int32` | `int32` | latency_ms, counts |
| `TEXT` (timestamp) | `string, format: date-time` | `string` | ISO 8601 |

**Naming**: proto3 fields are natively snake_case, matching the alignment
rules. No `json_name` / `proto_name` divergence will be introduced.
