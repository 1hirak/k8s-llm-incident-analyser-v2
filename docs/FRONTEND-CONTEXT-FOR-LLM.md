# K8s LLM Incident Analyser — Full Project & Frontend Report

> Purpose of this document: give an LLM (or a designer/developer) complete
> context about the project so it can propose and implement UI/UX and
> frontend improvements. It covers what the product does, the backend it
> talks to, and a file-level breakdown of the existing frontend.

---

## 1. What the product does

**K8s LLM Incident Analyser** is an LLM-assisted incident-response platform
for Kubernetes. When a pod enters `CrashLoopBackOff`, `ImagePullBackOff`, or
is repeatedly restarted, the platform:

1. Collects diagnostic evidence from the cluster via `kubectl` (current +
   previous logs, pod description, namespace events, restart count,
   container states).
2. Preprocesses it: keeps signal lines (error/exception/traceback/OOMKilled/
   CrashLoopBackOff…), keeps ±3 lines of context, caps logs at 100 lines,
   truncates pod status to 2,000 chars, and **redacts secrets** (passwords,
   API keys, DB URLs, auth headers, emails) before anything leaves the
   cluster.
3. Sends the safe `EvidencePackage` to an LLM (providers: `mock`, `openai`,
   `anthropic`, `deepseek`) with a strict JSON schema.
4. Returns a structured `IncidentReport`: summary, likely root cause,
   affected component, failure category, severity, confidence (0–1),
   supporting evidence, suggested fix, recommended kubectl commands, and
   human verification steps.
5. Persists the report to SQLite and streams pipeline progress live to the
   dashboard over SSE.

The platform also ships a **fault-injection demo system**: 25 common
Kubernetes failure scenarios (e.g. `05-oom`, `03-crashloop`,
`10-wrong-port`, and `25-readonly-filesystem`) that apply real
strategic-merge patches to a demo workload so users can generate failures
on demand and watch the analyser diagnose them. Different scenarios can be
active together; applying the same scenario twice returns HTTP 409. A reset
restores the healthy baseline.

### Analysis pipeline stages (the core UI metaphor)

`queued → collecting → processing → llm_call → persisting → done | failed`

Every stage transition is published to Redis pub/sub and proxied to the
browser as Server-Sent Events, so the UI shows a live pipeline timeline.

---

## 2. System architecture (what the frontend talks to)

Nine FastAPI microservices + Redis + SQLite + the Next.js frontend:

```
Browser → frontend (Next.js 15, :3000)
          → gateway-svc (:8000)  public API, auth, CORS, rate limit, SSE proxy
          ├→ orchestrator-svc (:8001)  job state machine + SSE pub/sub (Redis)
          │    ├→ collector-svc (:8002)  kubectl evidence collection
          │    ├→ processor-svc (:8003)  filtering + redaction
           │    └→ llm-svc (:8004)        LLM providers (mock/openai/anthropic/deepseek/openrouter)
           ├→ reports-svc (:8005)  SQLite (WAL) persistence
           └→ scenario-svc (:8006) kubectl patch fault injection
           ├→ remediation-svc (:8008) typed dry-run and approved Deployment changes
           └→ watcher-svc (:8007) read-only unhealthy-pod scan → orchestrator jobs
Redis :6379 — job state hashes (24h TTL) + pub/sub event channels
SQLite      — incidents + analysis_jobs (owned by reports-svc)
```

Everything is defined **contract-first** in `contracts/` (OpenAPI, SQL DDL,
Redis schema). The frontend's TypeScript types are generated from
`contracts/api/gateway.yaml` via `openapi-typescript`
(`npm run generate:types` → `src/types/api.d.ts`).

### Public API consumed by the frontend (gateway-svc, :8000)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + LLM provider + cluster connectivity |
| GET | `/api/targets` | List diagnosis targets by kind and namespace |
| POST | `/api/jobs` | Start analysis (202 + `job_id`) |
| GET | `/api/jobs` | List jobs (paginated, `status` filter) |
| GET | `/api/jobs/{job_id}` | Job state |
| GET | `/api/jobs/{job_id}/stream` | **SSE stream** of stage/done/failed events |
| GET | `/api/reports` | List report summaries (filters: namespace, pod_name, category, severity; paginated) |
| GET | `/api/reports/{incident_id}` | Full incident report |
| GET | `/api/stats?range=24h/7d/30d` | Dashboard aggregates |
| GET | `/api/scenarios` | List fault scenarios |
| POST | `/api/scenarios/{scenario_id}/apply` | Apply fault (409 if one active) |
| POST | `/api/scenarios/reset` | Reset cluster to healthy baseline |
| GET/POST | `/api/settings` | Get/update LLM provider config (keys never echoed) |
| GET | `/api/settings/providers` | List providers + key-availability status |
| POST | `/api/remediations` | Create a typed, server-side dry-run remediation proposal |
| GET | `/api/remediations/{remediation_id}` | Read proposal and audit state |
| POST | `/api/remediations/{remediation_id}/approve` | Approve and apply with `confirm: true` |
| POST | `/api/remediations/{remediation_id}/reject` | Reject a pending proposal |

All errors are RFC 7807 Problem Details (`type`, `title`, `status`,
`detail`, `instance`). Development can leave `GATEWAY_API_TOKEN` unset;
external-cluster deployments require Bearer-token access and restricted CORS.
The remediation APIs record `X-Operator-Id` as the proposal and approval audit
identity.

### Key data models (from the OpenAPI contract)

- **`incident_report`**: `incident_id` (UUIDv7), `incident_summary`,
  `likely_root_cause`, `affected_component`, `failure_category`, `severity`,
  `confidence` (0–1 float), `supporting_evidence[]` (min 1),
  `suggested_fix`, `recommended_commands[]` (kubectl strings),
  `human_verification_steps[]`, `created_at`.
- **`report_summary`**: list-view subset (id, namespace, pod_name, category,
  severity, confidence, summary, created_at).
- **`evidence_item`**: `source` (`pod_log` | `previous_pod_log` |
  `kubernetes_event` | `pod_status`), `pod`, `timestamp?`, `evidence` (text).
- **`job_state`**: `job_id`, `namespace`, `pod_name`, `status`, `stage?`
  (human-readable detail like "Calling DeepSeek deepseek-chat"),
  `incident_id?`, `latency_ms?`, `error?`, `created_at`, `updated_at`.
- **SSE payloads**: `sse_stage_event` (status + stage detail),
  `sse_done_event` (incident_id, failure_category, severity, latency_ms),
  `sse_failed_event` (error, latency_ms).
- **`stats_response`**: `total_reports`, `reports_24h`, `mean_latency_ms`,
  `mean_confidence`, `category_counts` (map category→count),
  `latency_series[]` ({timestamp, latency_ms}).
- **`scenario_summary`**: `scenario_id` (e.g. `05-oom`), `name`, `category`,
  `description`, `severity?`.
- **Enums**: 8 failure categories (`crash`, `config`, `dependency`,
  `network`, `image`, `resource`, `probe`, `unknown`); 4 severities (`low`,
  `medium`, `high`, `critical`); 7 job statuses; 4 evidence sources.
- **Pagination envelope**: `{ items, count, limit, offset }`.

---

## 3. Frontend tech stack

| Layer | Choice |
|---|---|
| Framework | **Next.js 15.3.4** (App Router), React 19.1, TypeScript 5.8 |
| Styling | **Tailwind CSS v4** (CSS-first config via `@theme` in globals.css, no tailwind.config file) |
| Components | **shadcn/ui** ("new-york" style, zinc base, CSS variables) on Radix UI primitives |
| Icons | `lucide-react` 0.525 |
| Charts | `recharts` 2.15 |
| Toasts | `sonner` |
| Font | Inter via `next/font/google` (exposed as `--font-inter`) |
| Logging | small console wrapper in `src/lib/logger.ts` (pino is a dependency) |
| Tests | Vitest 4 + Testing Library + jsdom (21 test files in `src/__tests__/`) |
| Build | `output: "standalone"` (for Docker), fetch full-URL logging enabled |
| Env vars | `NEXT_PUBLIC_API_URL` (browser, default `http://localhost:8000`), `INTERNAL_API_URL` (server-side fetches, default `http://gateway:8000`) |

Path alias `@/*` → `src/*`. shadcn aliases configured in `components.json`.
Types generated from OpenAPI: `src/types/api.d.ts` + hand-written aliases in
`src/types/index.ts`.

---

## 4. Design system ("Linear / Modern" DNA)

Defined in `src/app/globals.css`. **Dark-only** (`<html className="dark">`;
tokens live in `:root`, the `.dark` variant only toggles `dark:` utilities).
Stated intent in the CSS comments: "Deep space canvas (never pure black) + a
single indigo accent (#5E6AD2) used for interaction and ambient light, not
decoration."

### Color tokens

- Background: `#050506` / deep `#020203` / elevated `#0a0a0c`
- Foreground: `#edefef`; muted: `#8a8f98`
- Accent indigo: `#5E6AD2`; bright: `#6872D9`; glow: `rgba(94,106,210,0.3)`
- Surfaces: translucent whites `rgba(255,255,255,0.05)` / hover `0.08`
- Border: `rgba(255,255,255,0.06)`; input: `rgba(255,255,255,0.1)`
- Popover: `#0f0f12`; destructive: oklch red
- Chart palette: `--chart-1..5` = `#5E6AD2`, `#8B93E8`, `#8A8F98`, `#3D44A0`, `#B4B9F8`

### Signature effects

- **Layered ambient background** (in root layout, fixed, `aria-hidden`):
  radial-gradient base → SVG film-noise overlay at 1.5% opacity
  (`bg-noise` utility, kills gradient banding) → 64px technical grid at 2%
  (`bg-grid`) → two floating blurred light pools (indigo, animated with
  `float` 9s/12s keyframes, `motion-safe` only).
- **Multi-layer shadows**: `--shadow-card` (hairline white highlight ring +
  diffuse + ambient), `--shadow-card-hover` (adds indigo glow),
  `--shadow-glow` / `--shadow-glow-lg` (indigo ring + glow + inset
  highlight), `--shadow-inset-highlight`.
- **`text-gradient` utility**: vertical white gradient on headlines
  (`from-white via-white/95 to-white/70`, bg-clip-text).
- **Motion**: one easing token `--ease-expo-out: cubic-bezier(0.16,1,0.3,1)`
  ("expo-out, never bouncy"); radius scale from `--radius: 0.625rem`.
- Typography: Inter; heavy use of `font-mono` micro-labels with
  `tracking-[0.2em] uppercase` at 10–11px for kickers/eyebrows; IDs and
  kubectl targets rendered in mono.
- Status colors: emerald = success/healthy, red = failed/critical,
  amber = warning/high, sky/blue/violet = in-progress stages, zinc = neutral.

### Semantic color mapping for domain enums (in `status-badge.tsx`)

- Job status: queued=zinc, collecting=sky, processing=blue, llm_call=violet,
  persisting=amber, done=emerald, failed=red.
- Severity: low=zinc, medium=sky, high=amber, critical=red.
- Category: crash=red, config=amber, dependency=violet, network=cyan,
  image=orange, resource=emerald, probe=pink, unknown=zinc.
- Evidence source: pod_log=sky, previous_pod_log=indigo,
  kubernetes_event=amber, pod_status=violet.

---

## 5. App shell & navigation

`src/app/layout.tsx` (server component):

- Sets `<html lang="en" className="dark">`, Inter font, metadata with title
  template `"%s · K8s LLM Incident Analyser"`.
- Renders the layered ambient background, then `AppSidebar` (desktop) +
  `MobileNav` (mobile) + `<main>` centered `max-w-7xl px-4 py-8 md:px-8`,
  plus sonner `Toaster` at bottom-right.

`src/components/app-sidebar.tsx` (client):

- Fixed left sidebar `w-64`, `bg-background-deep/70 backdrop-blur-xl`,
  hidden below `md`.
- **Brand**: indigo gradient square with Terminal icon + "K8s Incident
  Analyser / LLM ops console".
- **Nav items** (7): Dashboard `/`, Analyse `/analyse`, Jobs `/jobs`, Reports
  `/reports`, Scenarios `/scenarios`, How it works `/how-it-works`, Settings
  `/settings`.
- Active state: white-ish bg + a glowing indigo 2px bar on the left edge.
- **HealthPill** at the bottom: polls `GET /health` on mount + every 30s;
  dot is emerald (ok), amber (cluster unreachable), red (gateway down),
  pulsing zinc (checking). Text shows `service version · provider` (+
  "cluster unreachable" when applicable).
- Mobile: sticky top bar with brand + health pill + horizontal scrollable
  nav row.

Other shell files: `src/app/loading.tsx` (skeleton dashboard),
`src/app/not-found.tsx` (centered 404 with back button),
`src/middleware.ts` (logs every request as JSON to console),
`src/instrumentation.ts` (uncaughtException/unhandledRejection handlers).

---

## 6. Page-by-page breakdown

### 6.1 Dashboard — `/` (`src/app/page.tsx`, **server component**)

- Fetches `getStats("7d")` + `listReports({limit: 6})` in parallel; on error
  renders `ErrorState`.
- If `total_reports === 0`: `EmptyState` with CTAs "Run an analysis" and
  "Browse scenarios".
- Otherwise:
  - `PageHeader` with kicker "Overview · Last 7 days" + "Run analysis" button.
  - 4 `StatCard`s (responsive grid sm:2 xl:4): Total reports, Reports (24h),
    Mean latency (formatted ms/s), Mean confidence (%) — each with icon +
    hint, hover lift (`hover:-translate-y-1`).
  - Charts row (`lg:grid-cols-5`): `CategoryChart` (bar, span 3) +
    `LatencyChart` (line, span 2), both inside `SpotlightCard`s.
  - "Recent reports" `SpotlightCard` with "View all" ghost button →
    `/reports`, containing `ReportsTable`.
- **Note**: the stats API supports `range=24h|7d|30d` but the UI hardcodes
  7d — no range switcher exists (improvement opportunity).

### 6.2 Analyse — `/analyse` (`src/app/analyse/page.tsx`, **client component**)

The flagship interactive page. Layout: `lg:grid-cols-[380px_1fr]`.

- Left card "New analysis": form with Namespace + Pod name inputs
  (defaults `demo` / `demo-app`), submit button with spinner state,
  destructive `Alert` for submit errors. Inputs disabled while running.
- Right side:
  - `idle` → `EmptyState` ("No analysis running").
  - running → `PipelineTimeline` card showing the 6 stages live.
  - `done` → emerald success card: latency, `CategoryBadge`,
    `SeverityBadge`, "View report" link + "Run another analysis" reset.
  - `failed` → destructive alert with the error message (+ latency) and
    reset button.
- State machine: `phase = idle | running | done | failed`; on submit calls
  `createJob()` then `streamJob(jobId, …)` (EventSource) which updates
  `status`/`stage` per SSE event; auto-closes on done/failed; transport
  errors synthesize a failed event ("Lost connection to the event stream…").
  EventSource closed on unmount via ref.

### 6.3 Jobs — `/jobs` (`src/app/jobs/page.tsx`, client)

- Header actions: status filter `Select` (All + 7 statuses) + refresh
  icon-button (spinning while loading).
- Table columns: Job (short UUID, mono), Target (`ns/pod`, mono), Status
  (`JobStatusBadge`), Detail (stage text or error, truncated), Latency,
  Created (UTC), Report (ghost "View" link when done).
- Pagination: offset-based, PAGE_SIZE=15, "Showing x–y of count" +
  Previous/Next buttons. Skeleton rows while loading; `EmptyState` when no
  jobs; `ErrorState` with retry on failure.
- **No live updates** — user must hit refresh to see job progress.

### 6.4 Reports list — `/reports` (`src/app/reports/page.tsx`, client)

- Filter form: Namespace input, Pod name input, Category select (8 +
  all), Severity select (4 + all), "Apply filters" submit, "Clear" ghost
  button when filters active. Draft vs applied filter state.
- `ReportsTable` + same offset pagination pattern as Jobs (PAGE_SIZE=15).
- `ReportsTable` columns: Summary (link to detail + short id), Category
  badge, Severity badge, Confidence (`ConfidenceMeter` 160px), Target
  (mono ns/pod), Created (UTC).

### 6.5 Report detail — `/reports/[id]` (`src/app/reports/[id]/page.tsx`, server component; has its own `loading.tsx`)

- 404 → `notFound()`; other errors → `ErrorState`.
- Header card: severity + category badges, summary as title,
  `ConfidenceMeter` ("LLM confidence").
- Two-column grid: "Likely root cause" (Search icon) + "Affected component"
  (Cpu icon, mono text).
- "Suggested fix" card (Wrench icon).
- `Tabs`: **Evidence (n)** / **Commands (n)** / **Verification (n)**.
  - Evidence: grid of `EvidenceCard` — source badge, pod name, timestamp,
    and the evidence text in a 128px-high `ScrollArea` with mono `pre`.
  - Commands: each command in a bordered code row with a `CopyButton`
    (clipboard, check icon for 2s); warning "Review before running — these
    modify cluster state."
  - Verification: list with square bullet icons.

### 6.6 Scenarios — `/scenarios` (`src/app/scenarios/page.tsx`, client)

- Header action: red-outlined "Reset cluster" button.
- Grid (`sm:2 xl:3`) of scenario cards: category + severity badges, name,
  mono scenario_id, description, "Apply" button in footer.
- Two `Dialog`s: apply confirmation ("This modifies live cluster state…")
  and reset confirmation (destructive button). Both disable buttons and show
  spinners while in flight.
- Feedback via **sonner toasts**: success (with `fault_description`),
  warning on 409 ("A scenario is already applied"), error otherwise.
- **Gap**: the UI does not show which scenario (if any) is currently active;
  the 409 is only surfaced after the user tries to apply.

### 6.7 Settings — `/settings` (`src/app/settings/page.tsx`, client, ~410 lines)

LLM provider configuration page (consumes the `/api/settings` endpoints).

- Security notice banner (ShieldCheck icon): "API keys are stored
  server-side… never shown again after you save them."
- **Provider picker**: grid (`sm:2 xl:4`) of radio-style selectable cards for
  the 4 providers (mock, OpenAI, Anthropic, DeepSeek). Each card: custom
  radio dot (indigo check when selected), provider name, mono id, an
  `AvailabilityBadge`, and the current model in mono. The active provider
  gets a floating emerald "Active" badge (`-top-2.5 right-3`); the selected
  card gets an indigo border/glow + inset highlight.
  - `AvailabilityBadge`: mock → sky "Always available"; key stored → emerald
    "Key configured" (Check icon); no key → amber "Key needed" (KeyRound icon).
- **Config card** for the selected provider:
  - Non-mock: API key `Input` (password type with eye/eye-off visibility
    toggle), placeholder "Leave empty to keep the stored key" when a key
    exists; red-outlined "Clear key" button (only when a key is stored) →
    destructive confirmation `Dialog`; helper text that keys are never
    displayed again.
  - Mock selected: sky info box "No configuration needed…" instead of the
    key field; model input disabled.
  - "Model override (optional)" input, placeholder shows the provider
    default; blank = provider default (sends `null`).
  - Footer: when the selection differs from the active provider, a hint
    "Saving will switch the active provider from X to Y"; Save button with
    spinner.
- Save flow: `saveSettings({provider, api_key?, clear_key, model})` → status
  replaced with response; key field cleared; sonner toasts for success /
  error. Selecting a different card resets the key input and model (model
  kept only when re-selecting the active provider).
- Loading: 4 skeleton cards; error: `ErrorState` with retry.
- Local sub-component: `AvailabilityBadge`.

### 6.8 How it works — `/how-it-works` (`src/app/how-it-works/page.tsx`, server, ~1100 lines)

A long-form, marketing/docs-style explainer page with its own metadata.
Content (all hardcoded): hero "Read this first" card with mental-model
diagram (fault.yaml → pod → RawEvidence → EvidencePackage → IncidentReport);
5-stage pipeline cards with connecting arrows; collection section (kubectl
call set, target resolution, RawEvidence fields); processing section
(select signal / redact secrets / build package, what the LLM sees, why
redaction is before the LLM); scenario catalogue (how faults are applied +
a 10-row table of every scenario with change/result/evidence); a complete
trace example (09-app-exception); "two kinds of errors" (target workload vs
pipeline errors + failure-path table); state & storage (Redis/SQLite/stdout,
live browser path, limitations); closing CTA card. Uses `SectionIntro`
(eyebrow/numbering), `CodeLine` mono blocks, color-coded stage tones
(amber/cyan/emerald/violet/indigo).

---

## 7. Component inventory

### Custom components (`src/components/`)

| Component | Type | What it does |
|---|---|---|
| `app-sidebar.tsx` | client | `AppSidebar` (desktop), `MobileNav`, `Brand`, `HealthPill` (30s polling) |
| `page-header.tsx` | server | kicker + gradient title + description + right-side actions slot |
| `stat-card.tsx` | server | metric card with icon chip, big tabular-nums value, hint; hover lift |
| `spotlight-card.tsx` | client | mouse-tracking radial indigo glow (320px, 12% opacity) painted via refs, no re-renders |
| `pipeline-timeline.tsx` | server | vertical 6-stage stepper; completed=emerald check, current=spinning loader (blue) or red X when failed, pending=hollow circle; connecting line |
| `status-badge.tsx` | server | `JobStatusBadge`, `SeverityBadge`, `CategoryBadge` (color maps in §4) |
| `reports-table.tsx` | server | shared reports table (dashboard + reports page) |
| `category-chart.tsx` | client | recharts BarChart, 280px, dashed grid, themed tooltip |
| `latency-chart.tsx` | client | recharts LineChart, monotone, no dots, latency-formatted Y axis |
| `confidence-meter.tsx` | server | Progress bar 0–100%; emerald ≥80, amber ≥60, red below |
| `evidence-card.tsx` | server | source badge + pod + timestamp + 128px ScrollArea mono pre |
| `copy-button.tsx` | client | clipboard copy with 2s check feedback; silent no-op on failure |
| `empty-state.tsx` | server | dashed-border centered state with icon + optional actions |
| `error-state.tsx` | client | destructive alert + Retry (defaults to `router.refresh()`); logs to console |
| `ui/*` | — | 14 shadcn primitives: alert, badge, button, card, dialog, input, progress, scroll-area, select, separator, skeleton, sonner, table, tabs |

### Lib layer (`src/lib/`)

- **`api.ts`**: `API_BASE_URL` switches server (`INTERNAL_API_URL` /
  `http://gateway:8000`) vs browser (`NEXT_PUBLIC_API_URL` /
  `http://localhost:8000`). `ApiError` class carrying status + RFC 7807
  problem. One generic `request<T>()` helper (JSON, `cache: "no-store"` on
  GETs, logs failures). Functions: `getHealth`, `createJob`, `listJobs`,
  `getJob`, `listReports`, `getReport`, `getStats`, `listScenarios`,
  `applyScenario`, `resetScenarios`, `getSettings`, `saveSettings`,
  `listProviders`.
- **`sse.ts`**: `streamJob(jobId, onEvent, onError)` — wraps `EventSource`
  on `/api/jobs/{id}/stream`, listens for `stage`/`done`/`failed` named
  events, JSON-parses payloads, auto-closes on terminal events, returns an
  unsubscribe function.
- **`utils.ts`**: `cn()` (clsx + tailwind-merge), `formatDateTime`
  (deterministic UTC "2026-07-21 10:05 UTC" — deliberately timezone-stable
  to avoid hydration mismatch), `formatChartTime`, `formatLatency`
  (ms→"1.2 s"), `formatPercent`, `shortId` (first 8 chars of UUID).
- **`logger.ts`**: level-based console JSON-ish logger.

### Types (`src/types/`)

`api.d.ts` is generated from `contracts/api/gateway.yaml`;
`index.ts` re-exports friendly aliases (`IncidentReport`, `JobState`,
`SseDoneEvent`, `ProviderInfo`, `ProviderConfigRequest`, `LLMConfigStatus`,
etc.) plus hand-written pagination envelopes
(`Paginated<T>`, `JobListResponse`, `ReportListResponse`),
`ScenarioListResponse`/`ProviderListResponse`/`ResetResponse`/`StatsRange`.

---

## 8. Rendering & data-flow patterns

- **Server components**: Dashboard, Report detail, How-it-works — fetch
  directly in the page with try/catch → `ErrorState` / `notFound()`.
- **Client components**: Analyse, Jobs, Reports, Scenarios, Settings —
  `useState` + `useCallback(load)` + `useEffect` data fetching; skeletons on
  first load; `ErrorState` with retry on failure; empty states with
  contextual CTAs.
- **No global state library, no React Query/SWR** — every client page owns
  its fetch lifecycle manually.
- **Pagination**: offset/limit, controlled by page state; filter changes
  reset offset to 0.
- **SSE**: only the Analyse page streams; `EventSource` lifecycle managed
  with a ref + unmount cleanup.
- **Feedback**: sonner toasts (scenarios + settings pages); inline alerts
  elsewhere. Timestamps always rendered in UTC for hydration safety.
- **Accessibility touches**: aria-labels on icon buttons, `aria-hidden` on
  decorative layers, `motion-safe` on ambient animations, semantic
  `<ol>` for the timeline.

---

## 9. Testing

Vitest + jsdom + Testing Library, 22 test files in `src/__tests__/`
covering: every page (dashboard, analyse, jobs, reports, scenarios,
settings, how-it-works), layout, api client, sse, utils, logger, middleware,
charts, status badges, spotlight card, reports table, pipeline/evidence
components. Run with `npm run test` (vitest run).

---

## 10. Known gaps & improvement opportunities (for UI/UX work)

1. **No stats range switcher** — API supports `24h|7d|30d`; dashboard is
   hardcoded to 7d.
2. **No live updates on Jobs page** — running jobs require manual refresh;
   could reuse the SSE stream or polling.
3. **No indication of the currently active scenario** — users only discover
   a conflict via a 409 toast after attempting to apply.
4. **No job detail view** — jobs table links only to reports when done;
   failed jobs show a truncated error in the row.
5. **Evidence display is plain mono text** in a small 128px scroll area —
   no log highlighting, line numbers, search, or expand.
6. **No deep-linking/state in URL** — filters, pagination, and tabs are
   component state only (no shareable URLs, back-button loses state).
7. **Dark-only theme** — intentional, but there is no light mode or theme
   toggle.
8. **Analyse form is free-text** — no pod autocomplete/validation against
   the cluster; deployment-name resolution happens server-side invisibly.
9. **Health pill is minimal** — no per-service status, no link to docs.
10. **Empty/error states are consistent but basic**; no retry backoff, no
    offline detection.
11. **Charts are minimal** (single bar + single line, fixed height, no
    legends/interactions beyond tooltip).
12. **Mobile nav is a horizontal scroll row** — works, but a drawer/sheet
    pattern may scale better (now more noticeable with 7 nav items).
13. **No full user-management UI**. External deployments require a gateway
    Bearer token; operator identities for remediation are passed through
    `X-Operator-Id`. OIDC-backed user management remains future work.
14. **Settings page: no "test connection" action** — users save a key and
    only find out it works when the next analysis runs; provider cards show
    no latency/model metadata beyond the default model string.

---

## 11. Repo quick map (frontend-relevant)

```
frontend/
├── src/app/            layout.tsx, globals.css, page.tsx (/), loading.tsx, not-found.tsx
│   ├── analyse/page.tsx        (client, SSE pipeline page)
│   ├── jobs/page.tsx           (client, jobs table)
│   ├── reports/page.tsx        (client, filterable reports)
│   ├── reports/[id]/page.tsx   (server, full report + tabs) + loading.tsx
│   ├── scenarios/page.tsx      (client, fault injection + dialogs + toasts)
│   ├── settings/page.tsx       (client, LLM provider config)
│   └── how-it-works/page.tsx   (server, long-form docs page)
├── src/components/     15 custom components + ui/ (14 shadcn primitives)
├── src/lib/            api.ts, sse.ts, utils.ts, logger.ts
├── src/types/          api.d.ts (generated), index.ts (aliases)
├── src/__tests__/      21 Vitest suites
├── contracts/api/gateway.yaml  (source of truth for types — one level up)
└── package.json        (next 15, react 19, tailwind 4, shadcn, recharts, sonner)
```

Backend services live in `services/{gateway,orchestrator,collector,processor,llm,reports,scenario}/`;
contracts in `contracts/`; docs in `docs/` (DEEP-DIVE.md is the canonical
architecture guide); fault patches in `k8s/scenarios/`.
