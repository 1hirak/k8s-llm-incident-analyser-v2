# Documentation Index

Everything written about this platform, and when to read it.

## Start here

| Document | Read it when… |
|----------|---------------|
| **[`DEEP-DIVE.md`](./DEEP-DIVE.md)** | You want to understand the **whole software** — design philosophy, architecture, a hop-by-hop trace of an analysis job, every service, the frontend, evaluation, testing, deployment, and an operational playbook. This is the flagship guide. |
| **[`Technical-Documentation.md`](./Technical-Documentation.md)** | You need the **exhaustive A-to-Z reference** — every endpoint, env var, schema, enum, algorithm, test suite, CI job, and deployment detail, verified against the current microservices codebase. |
| **[`INSTALLATION.md`](./INSTALLATION.md)** | You need to run the analyser in a container against an external Kubernetes cluster, configure RBAC, enable the watcher, or approve a remediation. |
| [`architecture.md`](./architecture.md) | You want the **10-minute** version: topology, responsibilities, data stores, pipeline stages. |
| [`../contracts/README.md`](../contracts/README.md) | You are changing any API, schema, enum, or infra — the contracts are the Single Source of Truth and change **before** code. |

## Focused Guides

| Document | Contents |
|----------|----------|
| [`ERRORS-AND-LOGGING.md`](./ERRORS-AND-LOGGING.md) | How the ten scenarios trigger workload failures, how `kubectl` evidence is collected, how logs are filtered and redacted, and how pipeline errors are surfaced and stored. |

## Reference

| Document | Contents |
|----------|----------|
| [`../contracts/api/*.yaml`](../contracts/api/) | OpenAPI 3.1 for every service boundary (gateway public API + 6 internal APIs, incl. SSE event schemas) |
| [`../contracts/database/schema.sql`](../contracts/database/schema.sql) | SQLite DDL — tables, CHECK constraints, indexes, triggers |
| [`../contracts/database/redis_schema.md`](../contracts/database/redis_schema.md) | Redis key patterns, TTLs, pub/sub channels, job lifecycle |
| [`../contracts/events/README.md`](../contracts/events/README.md) | Why AsyncAPI is deferred to v2 (+ migration plan) |
| [`../contracts/rpc/README.md`](../contracts/rpc/README.md) | Why proto3/gRPC is deferred to v2 (+ mapping rules) |
| [`report_schema.json`](./report_schema.json) | The `IncidentReport` JSON schema as sent to LLM providers |

## Advanced Topics

| Document | Contents |
|----------|----------|
| [`log-simulation-and-scale-strategies.md`](./log-simulation-and-scale-strategies.md) | 20 techniques for simulating K8s logs (programmatic, mutation, container-based, static, deterministic) + 20 strategies for handling log volumes that exceed LLM context windows (preprocessing, chunking, RAG, multi-agent, streaming, alternative representations) |

## Historical (v1 monolith — superseded)

| Document | Note |
|----------|------|
| [`index.html`](./index.html) | Rendered version of the v1 (single-process) documentation. Superseded by `Technical-Documentation.md`, which now documents the v2 platform. |
| [`Deep-Dive-05-OOM-Walkthrough.md`](./Deep-Dive-05-OOM-Walkthrough.md) | Narrative end-to-end trace of the OOM scenario (written against v1; the v2 service names differ, the pipeline stages are identical). |

---

**Rule of thumb**: code answers *how*, contracts answer *what*, and the
deep dive answers *why*. When they disagree, the code is right — then fix
the document (or the contract).
