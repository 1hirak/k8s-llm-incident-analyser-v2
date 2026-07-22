# Event Contracts — Deferred to v2

> **Status**: Deferred. v1 event payloads are documented in the OpenAPI SSE
> endpoint specification (`api/gateway.yaml` → `GET /api/jobs/{job_id}/stream`).

---

## Why AsyncAPI is not used in v1

v1 uses **Redis pub/sub** with **SSE (Server-Sent Events)** fanout to the
frontend. This is a lightweight, low-throughput event pattern that does not
require a dedicated message broker (Kafka, RabbitMQ, SQS).

The event payloads, channel patterns, and publish/subscribe semantics are
fully documented in:

1. **`api/gateway.yaml`** — the SSE endpoint's response schema defines the
   three event types (`stage`, `done`, `failed`) and their JSON payloads.
2. **`database/redis_schema.md`** — the Redis pub/sub channel pattern
   (`job:{job_id}:events`) and message format are specified here.

## When AsyncAPI will be introduced

AsyncAPI 2.6+ specs will be added in v2 if any of the following occur:

- Migration from Redis pub/sub to Kafka or RabbitMQ for event streaming
- Introduction of cross-cluster event propagation
- Need for event schema versioning and consumer-driven contract testing
- Throughput requirements exceeding Redis pub/sub capacity

## v2 Migration Plan (Reference)

When AsyncAPI is introduced, the following channels will be specified:

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `job.events.v1` | publish (orchestrator) / subscribe (frontend, gateway) | Job lifecycle events |
| `report.created.v1` | publish (reports-svc) / subscribe (frontend) | New report available |
| `scenario.applied.v1` | publish (scenario-svc) / subscribe (orchestrator) | Fault injected, ready for analysis |

All event payloads will remain snake_case per the alignment rules.
