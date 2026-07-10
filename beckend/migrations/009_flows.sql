-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 009 — the Flows engine (Phase F1, SYSTEM_ELEVATION_PRD.md §B1)
--
-- WHY: three uncoordinated automation systems already exist (inline funnel
-- code in main.py, the nexus/agents runtime, scheduler.py crons). Flows is
-- their unification, not a fourth system — built ON the existing spine:
-- `interactions` is already an append-only event log (the trigger outbox),
-- `agent_runs` is already a durable executor (the pattern flow_runs mirrors).
--
--   • flow_definitions — versioned flow graphs. `live` is independent of
--     `status`: a flow can be published (dispatched + executed for real) while
--     still NOT live (external actions — send_message/notify_operator — are
--     logged as 'shadow' steps, never actually sent). This is how F1 ships
--     "flows run headless... in shadow mode (log, don't send)" — enforced by
--     the runner checking THIS column, not a fragile per-call convention.
--     At most one PUBLISHED version per slug (partial unique index) — editing
--     a live flow must never mutate an in-flight run, which is why flow_runs
--     pins flow_id (a specific version row), not slug.
--
--   • flow_runs — one row per (flow version, person, trigger). dedup_key makes
--     the dispatcher's INSERT idempotent under replay (event dedup:
--     "event:<flow_id>:<interaction_id>"; state dedup:
--     "state:<flow_id>:<person_id>:<stage_entered_at>" — the natural
--     condition-episode boundary opportunities.stage_entered_at already
--     tracks, so a state-triggered flow fires once per stage-entry, not once
--     per sweep). causation_depth guards the feedback-loop blind spot (a flow
--     sends → lead replies → triggers a flow → sends…) — depth >= 2 runs are
--     never inserted for EVENT triggers (see nexus/flows/dispatcher.py).
--
--   • flow_run_steps — one row per executed node; the explainability record
--     (Action·Confidence·Reason culture, extended to automation). status
--     'shadow' means "the engine decided to send/notify and logged exactly
--     what it would have done, without touching a real channel" — the
--     evidence Erez reviews before ever flipping a flow's `live` flag.
--
--   • flow_timers — durable waits. The runner's timer-sweep flips
--     fire_at<=NOW() AND NOT fired rows back to flow_runs.status='running'.
--
-- Joins the Realtime publication exactly like agent_runs (migration 002) —
-- the cockpit will watch runs live once F2 ships the UI.
--
-- Additive + idempotent. RLS deny-all, same posture as every other table
-- (backend connects as postgres / BYPASSRLS). AFTER APPLYING: add
-- flow_definitions/flow_runs/flow_run_steps/flow_timers to _INTERNAL_TABLES
-- in main.py (done in this same PR — see main.py's _INTERNAL_TABLES set).
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS public.flow_definitions (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                             REFERENCES public.tenants(id),

    -- Stable identity across versions. Editing a flow creates a new version
    -- row (new id) with the same slug — never an UPDATE on a published row.
    slug         TEXT        NOT NULL,
    version      INT         NOT NULL,

    status       TEXT        NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft', 'published', 'paused', 'archived')),

    -- The kill switch F1 actually enforces: false = shadow (log, never send).
    -- Independent of `status` — a flow is dispatched/run while published
    -- REGARDLESS of `live`; `live` only gates whether action:send_message /
    -- action:notify_operator perform the real side effect.
    live         BOOLEAN     NOT NULL DEFAULT FALSE,

    name         TEXT        NOT NULL,
    description  TEXT,

    -- {"nodes":[{"id","type",...}], "edges":[{"from","to","when"}]}
    graph        JSONB       NOT NULL,
    -- Denormalized for the dispatcher's index — see nexus/flows/dispatcher.py.
    -- Event:  {"type":"event","kind":"<interactions.kind>"}
    -- State:  {"type":"state","predicate":{...}}  (nexus/flows/predicates.py DSL)
    trigger      JSONB       NOT NULL,

    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,

    UNIQUE (slug, version)
);

-- At most one PUBLISHED version per slug — the dispatcher's index.
CREATE UNIQUE INDEX IF NOT EXISTS flow_definitions_one_published_per_slug
    ON public.flow_definitions (slug) WHERE status = 'published';
CREATE INDEX IF NOT EXISTS flow_definitions_dispatch_idx
    ON public.flow_definitions ((trigger->>'type')) WHERE status = 'published';


CREATE TABLE IF NOT EXISTS public.flow_runs (
    id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                       REFERENCES public.tenants(id),

    -- Pins the exact VERSION that started this run — editing/republishing the
    -- flow can never mutate an in-flight run.
    flow_id                UUID        NOT NULL REFERENCES public.flow_definitions(id),
    person_id              UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    trigger_interaction_id BIGINT      REFERENCES public.interactions(id),

    status                 TEXT        NOT NULL DEFAULT 'running'
                                       CHECK (status IN ('running', 'waiting', 'success', 'stopped', 'failed')),
    cursor_node            TEXT,                       -- resumption point (NULL = start of graph)
    context                JSONB       NOT NULL DEFAULT '{}',  -- accumulated node outputs + signals

    -- Feedback-loop guard (PRD Blind Spot #3): a flow-caused interaction
    -- carries this depth+1 in its own trigger provenance; the event dispatcher
    -- refuses to trigger a NEW run at depth >= 2. 0 = human/webhook-caused.
    causation_depth        INT         NOT NULL DEFAULT 0,

    dedup_key              TEXT        UNIQUE,          -- idempotent dispatch, see header

    started_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS flow_runs_running_idx
    ON public.flow_runs (started_at ASC) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS flow_runs_person_idx
    ON public.flow_runs (person_id, started_at DESC);


CREATE TABLE IF NOT EXISTS public.flow_run_steps (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_run_id  UUID        NOT NULL REFERENCES public.flow_runs(id) ON DELETE CASCADE,

    node_id      TEXT        NOT NULL,
    node_type    TEXT        NOT NULL,
    -- 'shadow'  = an external action was decided but not performed (live=false)
    -- 'blocked' = the Policy Gate vetoed a live send (crisis/budget/quiet-hours/window)
    status       TEXT        NOT NULL
                             CHECK (status IN ('success', 'shadow', 'blocked', 'failed', 'waiting')),
    input        JSONB       NOT NULL DEFAULT '{}',    -- the node's static config
    output       JSONB       NOT NULL DEFAULT '{}',    -- what happened (incl. "would_send" previews)
    error        TEXT,

    at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS flow_run_steps_run_idx
    ON public.flow_run_steps (flow_run_id, at ASC);


CREATE TABLE IF NOT EXISTS public.flow_timers (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_run_id  UUID        NOT NULL REFERENCES public.flow_runs(id) ON DELETE CASCADE,
    fire_at      TIMESTAMPTZ NOT NULL,
    fired        BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS flow_timers_pending_idx
    ON public.flow_timers (fire_at) WHERE fired = FALSE;


-- ── Lock down — same deny-all posture as every other table ────────────────────
ALTER TABLE public.flow_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flow_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flow_run_steps   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flow_timers      ENABLE ROW LEVEL SECURITY;

-- ── Realtime — the cockpit watches runs live, exactly like agent_runs today ────
ALTER PUBLICATION supabase_realtime ADD TABLE flow_runs;


-- ── Seed: two system flows, PUBLISHED but NOT live (shadow mode, F1) ──────────
-- Erez reviews their shadow-mode run history (F2 UI) before ever flipping
-- `live` — no automated flow has sent a single real message before that.

INSERT INTO public.flow_definitions (slug, version, status, live, name, description, graph, trigger, created_by)
VALUES (
    'cooling-lead-nudge', 1, 'published', FALSE,
    'Cooling lead → notify operator',
    'A qualified/captured/briefed lead who has gone quiet for 36h+ notifies Erez to reach out — the highest-value state trigger this business has. Shadow mode: logs what it would notify, does not DM yet.',
    '{
      "nodes": [
        {"id": "t1", "type": "trigger"},
        {"id": "n1", "type": "action:notify_operator",
         "body": "A qualified lead has gone quiet 36h+ and needs a check-in — see the Work Queue."}
      ],
      "edges": [{"from": "t1", "to": "n1"}]
    }'::jsonb,
    '{
      "type": "state",
      "predicate": {"all": [
        {"field": "stage", "op": "in", "value": ["qualified", "captured", "briefed"]},
        {"field": "hours_since_last", "op": "gte", "value": 36}
      ]}
    }'::jsonb,
    'system'
)
ON CONFLICT (slug, version) DO NOTHING;

INSERT INTO public.flow_definitions (slug, version, status, live, name, description, graph, trigger, created_by)
VALUES (
    'booking-canceled-reengage', 1, 'published', FALSE,
    'Booking canceled → notify operator',
    'A canceled booking notifies Erez to personally re-engage — a canceled consultation is a live wire, not a bot conversation. Shadow mode: logs what it would notify, does not DM yet.',
    '{
      "nodes": [
        {"id": "t1", "type": "trigger"},
        {"id": "n1", "type": "action:notify_operator",
         "body": "A booking was just canceled — worth a personal follow-up while it is fresh."}
      ],
      "edges": [{"from": "t1", "to": "n1"}]
    }'::jsonb,
    '{"type": "event", "kind": "booking_canceled"}'::jsonb,
    'system'
)
ON CONFLICT (slug, version) DO NOTHING;

-- ── Config discoverability — both already default safely (OFF / 2) when
-- absent, in Python (nexus.flows.policy._flag_on / pressure_budget). Seeded
-- here purely so `SELECT * FROM app_config` shows Erez how to flip them. ────
INSERT INTO public.app_config (key, value, description) VALUES
    ('flows.enabled', 'false',
     'Flows engine master switch. false = dispatcher/runner sweeps no-op entirely (checked at claim time — flipping this off mid-flight parks running flows immediately, per SYSTEM_ELEVATION_PRD.md §B5.6).'),
    ('flows.pressure_budget', '2',
     'Max automated (agent/flow/cron) WhatsApp messages per person per rolling 7 days, across every system. Enforced by nexus.flows.policy.evaluate_send.')
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verification queries:
--
--   SELECT table_name FROM information_schema.tables
--   WHERE table_schema = 'public'
--     AND table_name IN ('flow_definitions','flow_runs','flow_run_steps','flow_timers');
--   -- Expected: 4 rows
--
--   SELECT slug, status, live FROM flow_definitions ORDER BY slug;
--   -- Expected: 2 rows, both status='published', live=false
--
--   SELECT * FROM pg_publication_tables
--   WHERE pubname = 'supabase_realtime' AND tablename = 'flow_runs';
--   -- Expected: 1 row (confirms Realtime is wired)
-- ─────────────────────────────────────────────────────────────────────────────
