# NEXUS V1 — Build Plan (locked 2026-06-10)

This is the governing document for the V1 build. It encodes the product thesis,
the locked decisions, the data model, the memory model, the cockpit design,
security/governance, and the sprint sequence. When implementation and this
document disagree, update one of them — never let them drift silently.

## 0. Product frame

**Long-term vision:** the central nervous system of the creator business —
four intelligence domains converging into a single operating layer: audience
intelligence, relationship intelligence, content intelligence, and business
intelligence. Every signal enters NEXUS; every decision is informed by it.
Used as an *architectural test*: every component must either feed signals in
or route decisions out; anything that does neither doesn't belong.

**V1 (this build):** the unified lead cockpit with light memory. Wins by making
Erez's current workflow dramatically simpler on day one while quietly seeding
the memory and intelligence foundation underneath.

**Three pillars** (every feature must serve one):
1. **Remembered relationships** — never forget a person; understanding compounds.
2. **Directed attention** — who needs me now, what's the move, what to ignore.
3. **Authentic leverage** — scale without going generic; human-gated, Erez's voice.

**North star:** booked consultations. **Value test for every screen:** "did this
make me more present with the people who matter, or just give me more to look at?"

## 1. Locked decisions

| # | Decision | Locked position |
|---|----------|-----------------|
| A1 | Tenancy | Single-tenant operationally; `tenant_id` column on every root table from migration 001 (seeded constant). No multi-tenant features. |
| A2 | In-app messaging | No. Cockpit = triage + intelligence; Erez replies in native apps. WhatsApp deep-links + copyable openers. |
| A3 | Infrastructure | Stay on Vercel (60s budget). Async work via cron endpoints (existing `crm-sync` pattern), not background threads — threads die post-response on serverless. |
| A4 | NL2SQL + Power BI | Frozen as-is. No rework, no removal. Cockpit reads via dedicated REST endpoints. Decide their fate after V1 ships. |
| M1 | WhatsApp capture | Out-of-system in V1. Modeled as identity channel + `wa_ref_code` so capture can be lit up later without re-architecture. |
| M2 | Identity model | Person-centric: `person` + `person_identity` UNIQUE(channel, external_id); phone is an identity channel = the deterministic join key; `wa_ref_code` embedded in wa.me prefill for manual linking. No auto-merge, ever — `merge_candidates` + cockpit review. |
| M3 | Profile shape | `summary` (Hebrew narrative) + `attributes` JSONB + `facts` JSONB list with provenance. Typed-core stays minimal; contents evolve without migrations. |
| M4 | Governance | Consent/disclosure lines (config-driven), crisis content never persisted to memory, person delete = full cascade erasure, RLS deny-all everywhere, retention policy documented (purge automation = V2). |
| P1 | Booking capture | Calendly webhook (signature-verified) + manual "mark booked" in cockpit. Unmatched bookings land in a linking inbox. |
| P2 | Operators | `operators` table + allowlist auth + nullable `assigned_operator_id` on opportunities. UI built single-operator. |
| P3 | AI disclosure | Honest: the bot presents as Erez's digital assistant (existing greeting already does). Recall is surfaced gently, never asserts unverified memory. |
| P4 | First demo | The bot visibly remembering a returning user (recall line) + bookings landing in the DB. Sprint 3 exit demo. |

**Architecture style:** capture events, don't event-source. Normal mutable
tables are operational truth; `interactions` is a parallel append-only signal
log for timeline + audit + future derivation. No queues, no brokers, no CQRS.

**Scale reality check (live DB, 2026-06-10):** sessions 47 · messages 59 ·
leads 7 · bot_events 18 — backfill is trivial, and any infrastructure beyond
Postgres tables is over-engineering. Content side: posts 709 · comments 11k ·
likers 268k · followers 20k — content signals are *enrichment*, never person
sources.

## 2. V1 scope

**In:** person spine + identity resolution · interactions log · opportunities
pipeline (engaged→qualified→captured→briefed→booked→done/lost) · bookings +
Calendly webhook · light memory (profile + session summaries, formation +
recall) · cockpit (Today queue, Person 360, Pipeline) · erasure endpoint ·
disclosure/consent lines · metrics strip.

**Out (explicitly):** embeddings/vector memory · content engine · theme mining ·
proactive/next-best-action · in-app messaging · multi-tenant
features · NL2SQL/Power BI rework · autonomous outbound anything · purge
automation (policy documented only). *(WhatsApp API — re-sequenced into Sprint 4
on 2026-06-13; no longer V1-out.)*

## 3. Architecture & repo layout

```
Vite React SPA (cockpit, RTL Hebrew)        Vercel project #2 (static)
        │  Supabase Auth JWT (Google)
        ▼
FastAPI on Vercel (existing project)        api/index.py → main.py
   main.py            — existing bot/webhooks/NL2SQL (frozen, strangler host)
   nexus/__init__.py  — new package, mounted into app
   nexus/db.py        — re-exports get_db_conn (single pool)
   nexus/identity.py  — resolve_or_create_person, phone identity, wa_ref, merge
   nexus/interactions.py — log_interaction(kind, …), opportunity stage machine
   nexus/memory.py    — formation (extends brief call), recall block, sweep
   nexus/bookings.py  — Calendly webhook handler, matching, manual booking
   nexus/cockpit_api.py — APIRouter /api/cockpit/* (JWT + operator allowlist)
   nexus/auth.py      — Supabase JWT verification dependency
        │
        ▼
Supabase Postgres 17 (project ixdsyikqnifviynunhxx)
   migrations: sql/v1_001_person_spine.sql (written)
               sql/v1_002_flow.sql · sql/v1_003_memory.sql (Sprint 3)
   cron: Vercel crons (daily) → /api/cron/memory-sweep, /api/cron/stale-close
         (upgrade path: Supabase pg_cron + pg_net for sub-daily)
```

**Strangler rules:** new code only in `nexus/`; `main.py` gets import + mount +
~6 one-line hook calls at hinge points. No refactor of working bot flows in V1.

**main.py hinge points to wire:**
1. Telegram webhook session entry → `resolve_or_create_person('telegram', chat_id)`
2. IG webhook session entry → `resolve_or_create_person('instagram', igsid, username)`
3. Lead capture (TG + IG paths) → phone identity + opportunity→captured + interaction
4. Icebreaker/trigger hit → opportunity 'engaged' + interaction
5. awaiting_context / brief delivery → formation piggyback (one extended LLM call)
6. wa.me CTA builder → append prefill text containing `wa_ref_code`

## 4. Data model

Migration 001 (written — `sql/v1_001_person_spine.sql`): `tenants`, `operators`,
`person`, `person_identity`, `merge_candidates`, `person_id` on sessions/leads.

### Migration 002 — flow (sketch)

```sql
interactions (
  id BIGINT IDENTITY PK, tenant_id, 
  person_id UUID REF person ON DELETE CASCADE,
  session_id UUID REF sessions ON DELETE SET NULL,
  channel TEXT, kind TEXT, occurred_at TIMESTAMPTZ DEFAULT NOW(),
  payload JSONB DEFAULT '{}', source TEXT DEFAULT 'live', dedup_key TEXT
)
-- UNIQUE(dedup_key) WHERE dedup_key IS NOT NULL; INDEX (person_id, occurred_at DESC)
-- kinds: session_started icebreaker_hit trigger_hit qualified captured
--        context_provided stage_change booking_created booking_canceled
--        outreach_click contacted note_added merged alert_sent crm_synced formation_run
-- payload = small refs/flags only (message ids, stage from/to), never message bodies.

opportunities (
  id UUID PK, tenant_id, person_id UUID NOT NULL REF person ON DELETE CASCADE,
  lead_id UUID REF leads ON DELETE SET NULL,
  stage TEXT DEFAULT 'engaged',     -- engaged|qualified|captured|briefed|booked|done|lost
  stage_entered_at, opened_at, closed_at, close_reason TEXT,
  source_channel TEXT, assigned_operator_id UUID REF operators,
  created_at, updated_at
)
-- Partial UNIQUE (person_id) WHERE closed_at IS NULL — one open episode per person.
-- Stage transitions audited as interaction kind='stage_change' {from,to,reason,by}.

bookings (
  id UUID PK, tenant_id,
  person_id UUID REF person ON DELETE CASCADE,        -- NULL until matched
  opportunity_id UUID REF opportunities ON DELETE SET NULL,
  source TEXT,                       -- calendly|manual
  external_id TEXT UNIQUE,           -- Calendly invitee uuid (idempotency)
  starts_at TIMESTAMPTZ, status TEXT DEFAULT 'scheduled',  -- scheduled|canceled|completed|no_show
  invitee_name TEXT, invitee_phone TEXT, invitee_email TEXT,
  matched_via TEXT,                  -- phone|email|manual|none
  created_at, updated_at
)
```

### Migration 003 — memory (sketch)

```sql
person_profile (
  person_id UUID PK REF person ON DELETE CASCADE, tenant_id,
  summary TEXT,                  -- Hebrew narrative, the hot-loaded context
  attributes JSONB DEFAULT '{}', -- relationship_status, core_concern, goals,
                                 -- objections[], prior_help, comm_style, …
  facts JSONB DEFAULT '[]',      -- [{fact, source_session_id, by:'ai'|'operator', at}]
  version INT DEFAULT 1, model_version TEXT,
  updated_by TEXT DEFAULT 'ai', updated_at
)
session_summaries (
  session_id UUID PK REF sessions ON DELETE CASCADE,
  person_id UUID REF person ON DELETE CASCADE, tenant_id,
  summary TEXT NOT NULL, topic TEXT, emotional_state TEXT, urgency INT,
  sensitive BOOLEAN DEFAULT FALSE, model_version TEXT, created_at
)
operator_notes (
  id UUID PK, tenant_id, person_id UUID REF person ON DELETE CASCADE,
  operator_id UUID REF operators, body TEXT NOT NULL, created_at
)
```

No vector columns in V1 — added by migration in V2 when volume justifies recall
beyond profile+summaries. `model_version` on every derived row = cheap
re-derivation provenance.

### Identity resolution rules (deterministic only)

1. `(channel, external_id)` exact match → person. Else create person — funnel
   channels only (instagram/telegram at first DM; web lazily at phone capture).
2. Phone captured → normalize E.164 (IL default) → upsert identity
   `(phone, E164)`. If that phone already belongs to a *different* person →
   write `merge_candidates(reason='shared_phone')`, do NOT merge.
3. Calendly invitee → match by phone identity, else email identity, else
   unmatched (cockpit linking inbox).
4. `wa_ref_code` → manual cockpit link (operator action, confidence='manual').
5. Content tables (likers/comments/followers) → read-time enrichment by
   username against IG identities. NEVER create persons from content.
6. Merge = manual cockpit action: moves identities/sessions/leads/opportunities/
   bookings/notes; merges profile (operator chooses); logs interaction
   kind='merged' with moved-id payload (audit = reversibility).

## 5. Memory model (V1 light memory)

**Formation A (inline, capture path):** the existing `_generate_lead_brief`
call extends to one JSON: `{topic, emotional_state, urgency, opening,
session_summary, profile_patch{summary, attributes, new_facts[]}}` — same
latency class (one LLM call), writes session_summaries + upserts
person_profile.

**Formation B (cron sweep, daily):** `/api/cron/memory-sweep` (cron_secret):
sessions with person_id, ≥2 user messages, idle >30min, no summary → summarize
in batches (≤5/run, fits 60s budget).

**Patch merge is code, not LLM:** operator-authored facts and operator edits
are never removed by an AI patch; AI proposes, code merges, version++.

**Crisis rule (hard):** if `is_crisis()` matched anywhere in the session →
`session_summaries.sensitive=true`, summary = neutral one-liner, NO details,
NO profile patch from that session.

**Recall (hot path):** for a known person, inject `profile.summary` + last 3
session summaries into the persona/RAG prompt with guardrails: reference
gently, never assert unverified memory, never mention "system/memory".
Gated by app_config `memory.recall_enabled` (default 'false' → flip after
manual spot-checks). `memory.formation_enabled` is the formation kill-switch.

**app_config keys added:** `memory.recall_enabled`, `memory.formation_enabled`,
`disclosure.line` (appended to greeting/funnel open), `consent.capture_line`
(shown at phone capture).

## 6. Command center (cockpit)

**Stack:** Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack
Query/Table + Recharts. **RTL Hebrew-first UI** (root dir="rtl", logical
properties; dates/numbers LTR-embedded). Dark, Linear/Stripe density. Separate
Vercel static project.

**Auth:** Supabase Auth (Google) → JWT → FastAPI dependency verifies
(SUPABASE_JWT_SECRET) + email ∈ operators. 401 otherwise. Cockpit origin added
to ALLOWED_ORIGINS.

**Screens (3 + shell, nothing more in V1):**
1. **Today (default)** — metrics strip (booked this week · live leads ·
   capture rate · median speed-to-lead) + action queue: open opportunities
   sorted urgency × wait, SLA timer chips, per-card: brief line, stage,
   WhatsApp deep-link (logs `outreach_click`), copy opener, mark
   contacted/booked/lost, open person.
2. **Person 360** — header (name, identities, stage, wa_ref) · editable
   profile panel (summary, attributes, facts + operator notes) · timeline
   (sessions → transcript drill-in, interactions, bookings) · actions: link
   identity by ref code, resolve merge candidate, delete person (erasure,
   double-confirm).
3. **Pipeline** — kanban by stage with aging colors; bookings list including
   the **unlinked-bookings inbox** (match-to-person action).

**Shell:** sidebar (Today/Pipeline/People/Settings-lite) + Cmd-K person search
(name/username/phone/ref code).

**API (`/api/cockpit/*`, all JWT-guarded):**

| Method | Path | Purpose |
|---|---|---|
| GET | /queue | open opportunities + brief/profile snippets, sorted |
| GET | /metrics/summary | north-star strip numbers |
| GET | /people?q= | search (name/username/phone/wa_ref) |
| GET | /person/{id} | profile, identities, opportunities, bookings, notes |
| GET | /person/{id}/timeline | sessions + interactions + bookings merged |
| GET | /session/{id}/messages | transcript drill-in |
| PATCH | /person/{id}/profile | operator edit (updated_by='operator') |
| POST | /person/{id}/notes | operator note |
| POST | /opportunity/{id}/stage | manual stage move {to, reason} |
| POST | /bookings | manual booking |
| POST | /bookings/{id}/link | link to person |
| POST | /identity/link | wa_ref/manual identity link |
| POST | /person/merge | resolve merge candidate {src, dst} |
| DELETE | /person/{id} | full erasure cascade |
| POST | /api/webhooks/calendly | (public path, signature-verified) |

**Metric definitions:** booked-this-week = bookings created this ISO week,
status='scheduled'. Live leads = open opportunities pre-booked. Capture rate =
existing `analytics.funnel_daily`. Speed-to-lead = median(captured →
first outreach_click|contacted interaction), 7-day window — honest proxy,
since WhatsApp replies are out-of-system.

## 7. Security & governance

- **RLS deny-all** on every new table (backend = postgres BYPASSRLS) — existing posture.
- **`_INTERNAL_TABLES` in main.py MUST add:** tenants, operators, person,
  person_identity, merge_candidates, interactions, opportunities, bookings,
  person_profile, session_summaries, operator_notes — so NL2SQL can never see
  or query them. Verify nexus_reader has zero grants on them (footer query in 001).
- **Webhooks:** Calendly HMAC signature (CALENDLY_WEBHOOK_SIGNING_KEY) — same
  rigor as Telegram secret / IG X-Hub-Signature-256.
- **PII discipline:** interactions.payload and logs carry refs/fingerprints,
  never message bodies (`_redact_text` convention continues).
- **Erasure:** DELETE /person/{id} removes — in order — messages, sessions,
  leads rows for the person, then person (cascades identities, profile,
  summaries, notes, opportunities, bookings). Logged to [AUDIT] stdout
  (interactions row would self-delete). Erasure available same-day from launch.
- **Consent/disclosure:** config-driven lines, on by default; bot already
  self-discloses as digital assistant.
- **Crisis:** never persisted to memory (see §5). Existing crisis routing unchanged.
- **Retention (documented policy, automation V2):** raw messages 24 months;
  memory until erasure; bookings PII indefinitely (business records).
- **New env vars:** SUPABASE_JWT_SECRET, CALENDLY_WEBHOOK_SIGNING_KEY; cockpit
  origin appended to ALLOWED_ORIGINS. (cron_secret already exists.)

## 8. Sprint plan

### Sprint 3 — "Spine + silent memory" (backend only; ~2–3 weeks solo)

| # | Ticket | Acceptance criteria |
|---|--------|---------------------|
| 3.0 | Apply migration 001 (after review) | Tables live; existing bot unaffected (smoke: TG + IG turn) |
| 3.1 | `nexus/` scaffold + identity module | resolve_or_create_person idempotent under the unique index; phone E.164 normalize; wa_ref generated on IG person creation |
| 3.2 | Migration 002 (flow tables) + apply | Constraints verified; one open opportunity per person enforced |
| 3.3 | Hinge-point wiring + stage machine + stale-close cron | Live TG/IG funnel produces person→opportunity→interactions trail end-to-end; pre-capture opps auto-close after 14 days idle |
| 3.4 | Backfill script | 47 sessions + 7 leads → persons/identities/opportunities; counts reconcile; re-runnable |
| 3.5 | Migration 003 + formation A/B + recall (flag off) | Capture turn writes summary+profile in same LLM call; sweep summarizes idle sessions; recall block renders correctly when flag on |
| 3.6 | Calendly webhook + wa_ref prefill + disclosure lines | Signature verified; phone-matched booking auto-advances opp to 'booked'; unmatched lands in inbox |
| 3.7 | _INTERNAL_TABLES guard + erasure endpoint + tests | NL2SQL schema excludes all new tables; erasure leaves zero rows for the person; pytest: identity, patch-merge, calendly match, erasure |

**Exit demo:** returning user on a second channel is recognized; recall line
references prior context (flag flipped for demo); Calendly booking appears as
'booked' with timestamps; metrics queryable by SQL.

### Sprint 4 — "WhatsApp + Qualification Flow" (re-sequenced 2026-06-13)

Pulled forward ahead of the cockpit (now Sprint 5). Lights up WhatsApp capture
(was M1 / §2-out / V2-deferred) and replaces the 2-turn funnel with the
insight-based qualification flow. Consequence: the cockpit oversight layer now
lands AFTER go-live, so the in-flow safety guards below are mandatory, not
optional.

**Locked decisions (2026-06-13):** Number = Coexistence on 0546150955 (keep the
WhatsApp Business app + Cloud API on the same number; verify IL
self-serve-vs-BSP eligibility at onboarding; build verifies on Meta's test
number meanwhile). Channels = WhatsApp + Telegram run the new flow; Instagram
stays on the current funnel. Interest signal (State 3→4) = small LLM 3-way
classifier (interested / declined / question-or-hesitation).

**Flow shape:** Understanding → Insight → Invitation → (wait for signal) →
Price. Empathy and price NEVER share a message. Only the insight (State 2) is
AI-generated; the opening, the bridge, the offer and the price (250₪) are
hardcoded. The insight reflects ONE of three axes (mind-vs-heart / exhaustion /
reality-vs-fantasy), no solutions, no banned phrases. Sits on the existing
`sessions.bot_state` TTL machine (24h = the WhatsApp service window) and the
`MessagingChannel` ABC seam — channel-neutral state names, not `wa_*`.

**Safety guards (mandatory — cockpit oversight comes later):** (1) crisis —
`is_crisis()` per-turn gate at webhook entry precedes insight generation
(already true for TG/IG; the WA webhook must call it too); (2) anti-cringe —
banned-phrase list enforced in CODE (post-gen validator + regenerate-once +
safe fallback), not prompt-only; (3) honesty — `disclosure.line` placement
decided on purpose (bot = Erez's digital assistant; no deceptive impersonation
per WhatsApp policy); (4) human-takeover — under Coexistence both Erez (app) and
the bot (API) can reply, so the bot backs off a conversation when Erez replies
manually.

| # | Ticket | Acceptance criteria |
|---|--------|---------------------|
| 4.1 | WhatsApp channel plumbing | Cloud API webhook (GET verify + POST receive, X-Hub-Signature-256); `WhatsAppChannel(MessagingChannel)`; Hook A person spine on first inbound (channel='whatsapp'); message-id dedup. Inbound WA → person resolved → reply sent, verified on the Meta test number. |
| 4.2 | Qualification state machine | story→insight→interest→price, channel-agnostic, on WA+TG; insight LLM call + banned-phrase validator; LLM interest classifier; crisis gate inherited; funnel hooks (engaged/qualified/captured). |
| 4.3 | Price → Calendly handoff + human-takeover | offered_price agreement → Calendly link (existing North Star); bot backs off on manual Erez reply (Coexistence). |
| 4.4 | Hardening + dogfood | Idempotency under Meta redelivery; 24h-window / template discipline; transcript spot-checks; live test with real leads. |

**Exit demo:** a real WhatsApp lead completes story → insight → interest → 250₪
offer → Calendly booking end-to-end, in Erez's voice, with crisis and
banned-phrase guards proven.

### Sprint 5 — "Cockpit" (~3–4 weeks solo)

| # | Ticket | Acceptance criteria |
|---|--------|---------------------|
| 5.1 | FE scaffold + Supabase Auth + JWT middleware | Erez signs in with Google; non-allowlisted email rejected server-side |
| 5.2 | Cockpit read APIs + Today queue + metrics strip | Queue sorted urgency×wait; SLA timers tick; numbers match SQL |
| 5.3 | Person 360 | Timeline + transcript drill-in; profile/facts editable (operator-wins persists); notes |
| 5.4 | Pipeline + bookings inbox + merge/link/delete | Kanban stage moves logged; unlinked booking linkable; merge resolves candidate; erasure works from UI |
| 5.5 | Cmd-K, RTL polish, deploy, dogfood | 5 consecutive real mornings used by Erez; fix-list triaged |

**Exit demo:** Erez runs an actual morning from the cockpit in ≤10 minutes.

### Deferred (V2 backlog, do not start)
Embeddings recall · theme mining · content studio · proactive
suggestions/NBA · purge automation · pg_cron sub-daily
sweeps · multi-operator UI.

## 9. UX principles

1. **Ambient, not immersive** — the 10-minute morning loop; if Erez lives in
   it an hour, it failed.
2. **Action-first** — every view answers "מה עכשיו"; describing without
   directing is the dashboard mirage.
3. **RTL Hebrew-first** — the operator thinks in Hebrew; UI chrome included.
4. **Keyboard-fast** — Cmd-K everywhere; queue navigable without mouse.
5. **Trust through provenance** — every AI-derived claim links to its source
   session; one click from "claim" to "what was actually said".
6. **Density with hierarchy** — Zoho-One-style top band (huge north-star
   numbers + trend), Linear-style restraint everywhere else.

## 10. Watch-list (failure modes to monitor during build)

- **Habit risk:** if Erez doesn't open the cockpit 5 mornings straight in
  dogfood week → cut scope, don't add features.
- **Recall tone:** one wrong/creepy "I remember" breaks authenticity —
  spot-check transcripts before flipping `memory.recall_enabled`.
- **Merge-queue noise:** if shared_phone candidates pile up, tighten creation
  rules before building more review UI.
- **Vercel 60s:** formation batch ≤5 sessions; if sweep starves, move to
  pg_cron sub-daily — not to threads.
- **Unlinked-bookings pile-up:** if >30% bookings unmatched, revisit Calendly
  form (require phone) before building matching heuristics.
- **Strangler discipline:** any PR touching main.py beyond hinge lines +
  mounts = scope alarm.
- **main.py size:** at 4,400 lines it's frozen, not endorsed — V2 decides
  extraction, never mid-V1.
