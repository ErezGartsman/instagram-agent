# System Elevation — PRD & Tech Spec

**Status:** Proposed 2026-07-09 · awaiting Erez review
**Scope:** Pillar A — Cockpit elevation to Tier-1 SaaS craft · Pillar B — the Flows automation engine
**Roadmap position:** Flows = Feature 2 of 3 (One Thread shipped, Signal follows)
**North star:** time-to-booked-consultation

---

## 0. The unconstrained audit — what the codebase actually is

### 0.1 Backend — a decision engine with an event-sourced heart (stronger than it knows)

| Layer | State | Verdict |
|---|---|---|
| Person spine | `person` / `person_identity` UNIQUE(channel, external_id) / `merge_candidates`, no auto-merge | **Excellent.** The identity backbone is Tier-1 grade. |
| Event log | `interactions` — append-only, deduped (`dedup_key`), typed kinds, payload ref-only (no PII) | **The buried treasure.** This is a domain event log. Flows can be built *on* it, not beside it. |
| Stage machine | `opportunities` — forward-only stages, one-open-per-person partial unique index | Replay-safe by schema, not by hope. Keep. |
| Action runtime | `agent_runs` / `agent_actions` / `info_requests` + Supabase Realtime on `agent_runs` | A durable, observable executor already exists. Flows reuses it. |
| Integration seam | `nexus/hooks.py` — the ONLY functions main.py calls; SAVEPOINT-guarded, never raises | The single choke point where every domain event is born. Perfect trigger emission site. |
| Ranking | `nexus/work_queue.py` — pure function, unit-tested, no I/O | The Action·Confidence·Reason culture. Flows must inherit this explainability bar. |
| **main.py** | **8,617 lines** — 40+ routes, webhooks, funnel logic, copy constants, NL2SQL, Kapso client | **The velocity ceiling.** Every feature lands here; every review pages through it. The strangler seam (`nexus/`) exists but routes never left. |
| Migrations | Split across `beckend/sql/` (v1_*) and `beckend/migrations/` (002–008, 007 absent), applied by hand via MCP | Works at one-operator scale; numbering drift is a quiet risk. |
| Automation today | **Three uncoordinated systems**: inline webhook funnel code in main.py, the `nexus/agents` runtime, and `scheduler.py` crons | The critical finding — see Blind Spot #1. Flows must unify these, or it becomes the *fourth*. |
| Tenancy | `tenant_id` = seeded constant; email allow-list is the real gate | Known, deferred by decision. No change proposed. |

### 0.2 Frontend — a locked design language executed unevenly

| Layer | State | Verdict |
|---|---|---|
| Design system | Midnight Instrument tokens in `cockpit/index.css` — disciplined, scoped, reduced-motion-safe | **Locked and good.** Pillar A builds *within* it. Zero token changes. |
| Landing page | GSAP theatre + WebGL particles, scene-mapped manifesto, lazy-split | The standard the cockpit is measured against. |
| Page architecture | `WorkQueuePage` 967 lines · `AnalyticsPage` 902 · `OverviewPage` 525 — each page a monolith | Primitives (glass panel, badge, meter, empty state) re-derived per page. `components/ui/` holds exactly one file. |
| Server state | Hand-rolled per page: `useQueueData.ts` is 184 lines of manual polling, signature-diffing, suppression refs | Heroic — and exactly what TanStack Query does better, everywhere, for free. |
| Error posture | `api.ts` swallows every failure into empty shapes (`[]`, `EMPTY_THREAD`) | **Silent-failure UI.** A decision engine that can't distinguish "no leads" from "API down" spends trust it can't afford. |
| Liveness | `agent_runs` has Realtime; the queue polls every 30s | Push exists in the stack; most surfaces don't use it. |
| Nav debt | `InboxPage` is a Ticket-5.2 placeholder that One Thread has since superseded | Dead door in a premium instrument. |
| Tests | Backend: 16 test files, real coverage. Frontend: none | The gap will bite hardest exactly when Flows authoring lands. |

### 0.3 The honest diagnosis

The landing page feels premium because every state is *authored* — nothing default, nothing accidental. The cockpit has a premium skin over unauthored states: default empty states, invisible errors, polling refreshes that blink data into place. **The gap is not visual design. It is craft depth: state honesty, motion continuity, and component discipline.** That is what Pillar A buys — and Pillar B's Flows engine is designed so its UI lands on those elevated primitives, not on today's monoliths.

---

## Pillar A — Cockpit Elevation: "the instrument earns the manifesto"

Not a re-skin. Midnight Instrument (CLAUDE.md §4) stays canon to the letter — void, glass, electric-blue signatures, Fraunces discipline, whisper budget. Elevation = the eight moves below, ordered by leverage.

### A1. Primitive extraction — one component library, zero re-derivation

Build `cockpit/components/ui/` into the real library (CVA variants on Midnight tokens):

`GlassPanel` (section/card/rail variants) · `Button` (primary/ghost/danger/icon) · `Badge` (stage/status/channel) · `ConfidenceMeter` (the mono-numeral + glow bar, extracted from queue) · `Skeleton` (cq-shimmer) · `EmptyState` / `ErrorState` (authored, with retry affordance) · `Kbd` · `DataTable` (tabular-nums, virtualized ≥ 50 rows) · `Sparkline`.

Then a strict rule enforced in review: **pages compose primitives; pages never restyle glass.** Refactor `WorkQueuePage`/`AnalyticsPage`/`OverviewPage` down to composition + feature logic (< 350 lines each).

### A2. Server-state spine — TanStack Query + Realtime invalidation

- Adopt `@tanstack/react-query`: queries keyed per resource (`['queue']`, `['dossier', id]`, `['thread', id]`), `staleTime` tuned per surface, focus-refetch and retry for free. Delete `useQueueData`'s manual machinery.
- Supabase Realtime channels (`agent_runs` today; add `opportunities`, `outbound_messages`, and Pillar B's `flow_runs`) publish → invalidate the matching query key. **Polling becomes the fallback, push becomes the norm.**
- Action Loop mutations go optimistic-with-rollback via `useMutation` — the queue FLIP animates the optimistic re-rank instantly.
- **End the silent-failure pattern:** `api.ts` functions throw typed errors; queries surface them; every page renders the authored `ErrorState`. An outage must *look like* an outage.

### A3. Motion continuity — route choreography within the whisper budget

- Shared-axis route transitions (220ms fade-slide via Framer Motion `AnimatePresence` on the outlet) — entering a dossier feels like moving *deeper*, not swapping documents.
- Staggered card entrances per route (existing `cq-rise`, 40ms stagger caps at 6 items).
- FLIP re-rank extended from the queue to every ranked list (pipeline columns, analytics movers).
- Data updates *transition* (count-up on stat deltas ≤ 400ms, mono numerals) — a live instrument, never a blinking refresh. All of it dies under `prefers-reduced-motion`, as today.

### A4. State honesty — every surface authored in four states

Loading / empty / error / first-run designed per page, not defaulted. Empty states carry the next action ("No one is waiting. The last lead was handled 2h ago → View pipeline"). First-run states teach the surface once. This is the single highest-leverage premium signal — it is what separates the landing page from the cockpit today.

### A5. Typographic + density rhythm

4pt baseline grid utilities; a declared type scale (11/12/13/15/18/24 + Fraunces display) replacing per-page ad-hoc sizes; `tabular-nums` audited onto every numeral; line-height and letter-spacing pass on dense tables. Two weights, sentence case — as locked.

### A6. Command-first operation

⌘K palette grows from search into *actions* ("snooze…", "advance to captured", "trigger agent", "run flow…" once Pillar B lands). Full keyboard traversal of the queue (j/k/enter/s). The palette is the power user's front door; a Tier-1 instrument is operable without the mouse.

### A7. Retire the dead door

Remove Inbox from nav (`shell/nav.ts`); `/app/inbox` redirects to the queue. One Thread inside the dossier *is* the inbox. Placeholder pages are anti-premium.

### A8. Performance & a11y budget (invisible craft)

Budgets enforced in CI: initial cockpit chunk < 250KB gz; route LCP < 1.5s; virtualized long lists; `backdrop-blur` stays section-only (as locked); focus-visible + aria pass on the new primitives; axe clean. Add Vitest + Testing Library for the primitives and the query hooks — the frontend's first tests, landing where Flows authoring will need them most.

**Pillar A acceptance:** every route survives the four-state audit · zero raw hex in components · zero hand-rolled pollers · route transitions ship · nav has no placeholders · CI enforces budgets.

---

## Pillar B — Flows: automation as data on the event spine

### B0. The paradigm decision

The obvious build — a workflow engine with its own triggers, its own queue, its own send path — would be the **fourth** parallel automation system. The codebase already has the three hard parts of a workflow engine, shipped and battle-tested:

1. **An append-only event log** — `interactions` (typed kinds, deduped, replay-safe). These *are* the triggers.
2. **A durable, observable executor** — `agent_runs`/`agent_actions` + Realtime. This *is* the run log.
3. **Channel send adapters with idempotency** — One Thread Phases 2–3 (client_token dedupe, 24h-window awareness). These *are* the actions.

So Flows is three thin, well-defined layers on top:

> **Flows-as-data** (versioned JSONB graphs) · **execution-as-reconciliation** (DB-queue sweeps — no new infra on Vercel serverless) · **safety-as-one-policy-gate** (every automated outbound from *any* system passes one gate).

### B1. Data model (migration `009_flows.sql`, additive)

```sql
flow_definitions (
  id UUID PK, tenant_id UUID DEFAULT const,
  slug TEXT NOT NULL,                  -- stable identity across versions
  version INT NOT NULL,                -- published versions are IMMUTABLE
  status TEXT CHECK (status IN ('draft','published','archived')),
  name TEXT, description TEXT,
  graph JSONB NOT NULL,                -- nodes[] + edges[]; validated in code
  trigger JSONB NOT NULL,              -- denormalized for the dispatcher's index
  created_by TEXT, created_at, published_at,
  UNIQUE (slug, version)
)
-- at most one published version per slug (partial unique index)

flow_runs (
  id UUID PK, flow_id UUID REFERENCES flow_definitions,  -- pins the VERSION
  person_id UUID REFERENCES person ON DELETE CASCADE,
  trigger_interaction_id BIGINT REFERENCES interactions,
  status TEXT CHECK (status IN ('running','waiting','success','stopped','failed')),
  cursor_node TEXT,                    -- resumption point for waits
  context JSONB DEFAULT '{}',          -- accumulated node outputs
  causation_depth INT NOT NULL DEFAULT 0,   -- loop guard (Blind Spot #3)
  dedup_key TEXT UNIQUE,               -- (flow_id, trigger_interaction_id) → at-least-once safe
  started_at, completed_at
)

flow_run_steps (
  id UUID PK, flow_run_id UUID REFERENCES flow_runs ON DELETE CASCADE,
  node_id TEXT, node_type TEXT,
  status TEXT, input JSONB, output JSONB, error TEXT, at TIMESTAMPTZ
)

flow_timers (                          -- durable waits; swept by scheduler
  id UUID PK, flow_run_id UUID REFERENCES flow_runs ON DELETE CASCADE,
  fire_at TIMESTAMPTZ NOT NULL, fired BOOLEAN DEFAULT FALSE
)
```

RLS deny-all like every table. `flow_runs` joins the Realtime publication → the cockpit watches runs live, exactly like `agent_runs` today.

### B2. Trigger taxonomy

| Type | Source | Examples |
|---|---|---|
| **Event** | new `interactions` row matching kind (+ optional payload filter) | `captured`, `outreach_click`, `booking_canceled`, `stage_change{to:qualified}` |
| **State** | evaluated by the sweep, not by an event | "stage = qualified AND quiet ≥ 36h" — the *cooling lead*, the highest-value trigger this business has |
| **Schedule** | cron expression via `scheduler.py` | "daily 08:00 Asia/Jerusalem: leads booked tomorrow → prep note" |
| **Manual** | cockpit / ⌘K / queue action | "Run *re-engage* on this person" |

State triggers fire once per (flow, person, condition-episode) — a `dedup_key` of `(flow, person, condition_entered_at)` prevents re-firing every sweep while the condition holds.

### B3. Execution model — reconciliation, not daemons

Vercel serverless + `scheduler.py` means no long-lived workers. The engine is two idempotent sweeps (piggybacking the existing cron seam, then an every-minute Vercel cron):

1. **Dispatcher sweep** — reads `interactions` past a stored watermark (`app_config`), matches published flow triggers, inserts `flow_runs` (`ON CONFLICT (dedup_key) DO NOTHING`). The append-only log *is* the outbox — no dual-write problem, and events emitted while the dispatcher was down are simply picked up on the next sweep.
2. **Runner sweep** — claims `flow_runs WHERE status IN ('running') FOR UPDATE SKIP LOCKED`, executes nodes from `cursor_node`, writes a `flow_run_steps` row per node, parks on `waiting` + a `flow_timers` row for waits. Each step idempotent by `dedup_key` discipline (send dedupe already exists in `outbound_messages.client_token`).

At-least-once delivery with idempotent steps — the same guarantee posture `hooks.py` already established (idempotence by schema, not hope). Failure isolation: one poisoned run fails alone; three consecutive step failures → run `failed`, surfaced in the cockpit, never retried silently forever.

### B4. Node types (V1 — deliberately small, each one explainable)

| Node | Semantics |
|---|---|
| `trigger` | Entry, one per flow |
| `condition` | Predicate over the Person-360 read model — a **JSONB predicate DSL** (`{"all":[{"field":"stage","op":"eq","value":"captured"},{"field":"hours_since_last","op":"gte","value":36}]}`), evaluated by a safe interpreter in `nexus/flows/predicates.py`. **Never free-form code.** Fields come from a typed registry (the `ai_planner` capability-registry pattern, reused). |
| `branch` | condition → true/false edges |
| `wait` | duration or until-timestamp; durable via `flow_timers` |
| `action:send_message` | channel adapter via the **Policy Gate** (B5) — operator-voice templates with variables; **never bot-persona counseling** (intake lock upstream, always) |
| `action:advance_stage` | forward-only machine — illegal moves no-op, logged |
| `action:add_note` / `action:set_flag` | writes `interactions` (kind `note_added` / `flag_set`) |
| `action:notify_operator` | Telegram DM to Erez / hot-lead toast — the human-in-the-loop node |
| `action:run_agent` | hand off to the `nexus/agents` runtime |
| `ai:evaluate` | one planner call → structured verdict into run context (e.g. "classify reply intent") — bounded, never generates outbound copy in V1 |

Every executed node records input → output → why: the Action·Confidence·Reason culture extended to automation. **A flow run must be as explainable as a queue recommendation.**

### B5. The Policy Gate — the load-bearing discovery

One module — `nexus/flows/policy.py` — through which **every automated outbound message passes**, whatever originated it (flow, agent, cron, future Signal):

1. **Crisis-gate precedence** — absolute, upstream, untouched (the standing lock).
2. **Intake-assistant lock** — automated sends are operator-voice logistics only; the bot persona stays silent after the handoff ACK. Structurally enforced, not per-flow-remembered.
3. **Pressure budget** — max N automated messages per person per rolling 7 days **across all systems** (default 2, `app_config`). Per-flow limits don't compose; per-person budgets do.
4. **Quiet hours** — no automated sends 21:00–09:00 Asia/Jerusalem (leads are Hebrew-speaking locals); defer to a timer, don't drop.
5. **Channel eligibility** — the 24h WhatsApp window logic One Thread already built.
6. **Kill switches** — per-flow pause and a global `flows.enabled` flag, checked at claim time (mid-flight runs park immediately).

Blocked sends are recorded on the run step (`blocked: pressure_budget`) — visible, never silent. In the same stroke, the qualification agent and SLA crons are re-pointed through the gate: **Flows ships as the unification of Nexus automation, not an addition to its fragmentation.**

### B6. Simulation & replay — the moat

`interactions` is append-only history, so a draft flow can be **replayed against the last 90 days of real events** before it touches a human:

> "This flow would have fired **34** times · sent **28** messages (**6** blocked: 4 pressure budget, 2 quiet hours) · advanced **11** stages · est. cost of waits: median 41h to next touch."

Dry-run = dispatcher + runner in `simulate=True` (no writes, no sends, verdicts recorded to an ephemeral report). **Publishing requires a simulation pass** — the publish dialog *is* the simulation report. This single feature separates a serious automation engine from a toy, and only an event-sourced spine makes it nearly free.

### B7. Canvas UI — Midnight Instrument, extended not amended

- **Library:** `@xyflow/react` (React Flow), fully themeable — glass nodes on the void, electric-blue edges, one neon shadow on the selected node. Lazy-split like recharts (never in the cockpit's initial chunk).
- **Nav:** Studio group → "Flows": list (status, last fired, 7-day fire count sparkline) → canvas editor → run history.
- **Run inspector:** click any run → the canvas replays its path, per-node input/output/why; blocked steps show the policy reason. Live runs animate via Realtime on `flow_runs`.
- **Node palette** = the B4 registry, rendered from the same typed metadata the backend validates against (one source of truth; the `ai_planner` registry pattern again).
- Motion within the whisper budget: `cq-crystallize` on node add, edge draw ≤ 300ms, no ambient canvas animation.

### B8. Explicit non-goals (locks respected)

- **No conversational bot-building.** Flows automates logistics and operator leverage; it will never re-wire the retired qualification funnel (Ticket 4.6 lock).
- **No auto-generated outbound copy in V1** — templates with variables only; `ai:evaluate` classifies, it does not speak.
- No arbitrary code nodes, no third-party action marketplace, no multi-tenant flow sharing (tenancy stays deferred).
- No new infra: Postgres + Vercel cron + the existing scheduler. No Redis, no queue service, no state-machine SaaS.

---

## Blind spots surfaced (the ones that weren't in the brief)

1. **Automation fragmentation** — main.py inline funnel code, `nexus/agents`, and crons act on leads with no shared safety layer. Flows without the Policy Gate would make it four systems double-messaging the same human. *Addressed: B5.*
2. **Message pressure doesn't compose** — per-flow rate limits still let three polite flows harass one person. Budgets must be per-person, cross-system. *Addressed: B5.3.*
3. **Feedback loops** — a flow sends → lead replies → inbound interaction → triggers a flow → sends… `causation_depth` on runs (flow-caused interactions carry provenance; depth ≥ 2 cannot trigger event flows). *Addressed: B1.*
4. **Version pinning** — editing a live flow must not mutate in-flight runs; hence immutable published versions and runs pinned to `flow_id`. *Addressed: B1/B7.*
5. **Silent-failure UI** — empty-shape-on-error means Erez cannot distinguish a quiet day from a dead API. For a decision instrument this is a trust defect, not a style choice. *Addressed: A2.*
6. **The main.py ceiling** — Flows endpoints must NOT land in the 8,617-line monolith. Enabling work: extract `beckend/routers/` (`cockpit.py`, `webhooks.py`, `flows.py`) via FastAPI `APIRouter` — the strangler seam finally strangling. *Sequenced: E0.*
7. **Migration hygiene** — two SQL directories, hand-applied, 007 missing. Adopt one numbered `migrations/` dir + a tiny applied-versions table before 009 lands. *Sequenced: E0.*
8. **Quiet hours & locale** — automation that messages at 02:00 or in the wrong register destroys the personal-consultant brand the intake pivot protected. *Addressed: B5.4.*
9. **The Inbox placeholder** — nav debt that One Thread already paid for. *Addressed: A7.*
10. **Frontend testlessness** — Flows authoring is the first surface where a UI bug silently corrupts an automation graph. Tests arrive with the primitives, before the canvas. *Addressed: A8.*

---

## Sequencing — six shippable phases

| Phase | Ships | Contents |
|---|---|---|
| **E0 — Enabling** | invisible, 1 PR each | `routers/` extraction (cockpit + webhooks + flows skeleton) · migration runner + dir consolidation · TanStack Query spine + error surfacing (A2) |
| **E1 — Instrument** | visibly better cockpit | Primitive library (A1) · four-state audit (A4) · type/density pass (A5) · Inbox retirement (A7) |
| **E2 — Choreography** | the premium *feel* | Route transitions + FLIP everywhere + live-value motion (A3) · ⌘K actions + keyboard queue (A6) · CI budgets + first frontend tests (A8) |
| **F1 — Engine** | flows run headless | `009_flows.sql` · predicate DSL · dispatcher + runner sweeps · **Policy Gate wired for flows AND existing agents/crons** · two seeded system flows (cooling-lead nudge → notify_operator; booking-canceled → re-engage) run in shadow mode (log, don't send) |
| **F2 — Glass** | flows become visible | Flows list + read-only canvas + run inspector with Realtime · shadow-mode reports reviewed in the cockpit |
| **F3 — Authoring** | the full feature | Canvas editing · simulation-gated publishing (B6) · versioning · kill switches · pressure-budget settings surface |

Each phase is independently valuable; nothing blocks on a big-bang. F1's shadow mode means the engine proves itself on real events for a week before its first real send — the same evidence-first posture as the SLA work.

## Success metrics

- **North star:** time-to-booked-consultation (existing measure, before/after F3).
- Cooling leads re-engaged within 24h: from manual-only → ≥ 90% automated-or-surfaced.
- Zero policy violations: no automated send past pressure budget / quiet hours / intake lock (hard assert in tests + audited in `flow_run_steps`).
- Cockpit: every route passes the four-state audit; route-change P95 < 300ms; initial chunk < 250KB gz.
- Explainability: 100% of flow runs reconstructable node-by-node from `flow_run_steps`.

---

*Prepared by Claude Fable 5 after a full-codebase audit (frontend shell/pages/lib, backend main.py + nexus/ + both SQL trees, One Thread PRD lineage). Standing locks honored throughout: intake-assistant pivot (Ticket 4.6), Midnight Instrument (§4), Copilot drafts-never-auto-send, deferred tenancy.*
