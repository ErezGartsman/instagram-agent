# NEXUS V1 — Integration Map (ticket 3.3 contract)

Complete audit of every production flow the nexus wiring touches, compiled from
a full read of main.py (4,401 lines) on 2026-06-10, BEFORE any main.py edit.
This document is the contract for ticket 3.3: wire exactly these hooks,
nothing else. All locations are in `main.py` unless stated.

## Headline finding — the wiring collapses to 2 chokepoints + 7 small touches

`_db_get_or_create_channel_session` is the single session resolver for BOTH
Telegram and Instagram, and `_finalize_lead` is already the "single post-save
side-effect funnel for ALL capture paths" (its own words). Hooking those two
functions covers identity resolution on every turn and all four lead-capture
paths without touching any state-machine branch. Everything else is small,
best-effort, additive lines.

## Hook inventory (the only main.py edits permitted in 3.3)

| ID | Location | Current responsibility | Nexus hook | Risk | Rollback |
|----|----------|------------------------|------------|------|----------|
| G | module tail / app wiring | — | `import nexus.db; nexus.db.configure(get_db_conn)` (+ router mounts later) | Low | remove lines |
| A | `_db_get_or_create_channel_session` (2218) | race-safe session get-or-create for TG+IG (used at 2907→3411, 3283, 3955, 3972) | after resolve: best-effort `resolve_or_create_person(conn, channel, contact_id)` + stamp `sessions.person_id` when NULL | **Medium** (runs on every TG/IG turn; must be try/except-wrapped so identity failure never breaks the bot) | remove block; orphan person rows are harmless — no legacy code reads nexus tables |
| B | `_finalize_lead` (2710) | post-capture side-effects for ALL 4 capture paths: owner alert → CRM → bookkeeping, all best-effort, after user ack | append capture block: resolve person → `attach_phone_identity` → stamp `leads.person_id` → `get_or_open_opportunity` → `advance_stage('captured')` → log `captured` interaction (`dedup_key=f"captured:{lead_id}"`) | **Low** (already inside the best-effort post-ack zone) | remove block |
| C1 | IG cold-entry branch (4146–4175) | icebreaker/trigger gate → awaiting_contact; `_track("icebreaker_hit")` at 4173 | best-effort: open opportunity ('engaged') + log `icebreaker_hit`/`trigger_hit` interaction | Low | remove lines |
| C2 | TG awaiting_qualification answered (3425–3435) | story captured → contact keyboard | best-effort: `advance_stage('qualified')` + `qualified` interaction | Low | remove lines |
| C3 | TG offer AFFIRM (3458–3468) + safety-net (3615–3625); IG offer AFFIRM (4005–4014) | offer accepted → contact keyboard | best-effort: open opportunity + `advance_stage('qualified')` | Low | remove lines |
| C4 | TG booking-intent entry (3638–3658) | deterministic funnel entry → awaiting_qualification | best-effort: open opportunity ('engaged') + `trigger_hit` interaction (channel=telegram) | Low | remove lines |
| C5 | IG awaiting_context (4118–4133) | one-shot topic line → `_deliver_lead_brief`; `_track("context_provided")` at 4126 | best-effort: `advance_stage('briefed')` + `context_provided` interaction | Low | remove lines |
| D | `InstagramChannel.send_contact_prompt` / `_contact_buttons` (3235/3255) | builds the wa.me CTA button — the PRIMARY live capture CTA | append URL-encoded `?text=` prefill containing the person's `wa_ref_code` (lookup by igsid; fall back to plain wa.me on ANY error) | **Medium** (malformed URL breaks the main conversion CTA — device-test before deploy) | revert to plain `wa.me/<number>` (1 line) |
| E | `_generate_lead_brief` (2788) / `_deliver_lead_brief` (2829) | post-capture brief: one LLM call → Telegram edit-in-place + HubSpot note | extend prompt JSON with `session_summary` + `profile_patch` keys; write session_summaries + upsert person_profile after brief delivery; gated by `memory.formation_enabled` | **Medium** (changes a live LLM call/JSON contract — keep old keys, new keys optional; parse failure already degrades) | flag off / revert prompt |
| F | `_rag_generate` (1739) / `_bot_triage_reply` (1801) | the two live persona prompts (web RAG + TG triage) | inject optional recall block (profile summary + last summaries) for known persons; gated by `memory.recall_enabled`, default OFF | **Medium-High** (changes the bot's voice — the authenticity risk) | flip flag off (no deploy needed; app_config TTL ≤ 5 min) |
| — | `POST /api/webhooks/calendly` + cron routes | **net-new** (Calendly appears only in comments at 3100/3177 — zero processing code exists) | new routes in nexus/bookings.py + memory-sweep/stale-close cron endpoints, mounted in main.py | Low (pure additive) | unmount |

Wiring order (de-risk): G → B → A → C1–C5 → D → (3.5:) E → F.

## Capture-path map (all covered by Hook B — no direct edits)

| Path | Lead INSERT | _finalize_lead call | Notes |
|------|-------------|---------------------|-------|
| TG native contact share | 3343 | 3354 | only path with `name`; phone from `contact.phone_number` (3332) |
| TG awaiting_contact typed phone | 3539 | 3547 | regex `_extract_phone_from_text` (2191) |
| TG regex fallback (normal chat) | 3596 | 3602 | phone volunteered mid-conversation |
| IG awaiting_contact typed phone | 4073 | 4086 | sets `awaiting_context` after; `_track("lead_captured")` at 4089 |

## Sessions map

| Site | Function | V1 hook |
|------|----------|---------|
| Web/API session create | `_db_create_session` (444) via POST /api/sessions (1471) | **None** — web persons are lazy-at-capture, and no web capture path exists |
| TG/IG session resolve | `_db_get_or_create_channel_session` (2218) | Hook A (covers all 4 call sites incl. crisis/clear paths) |
| last_active / bot_state | `_db_touch_session` (509), `_db_set_session_state` (2278) | None |

## Phone handling — the two-normalizer rule

- `_extract_phone_from_text` (2191) + `_IL_PHONE` (2010): extraction from typed
  text. Untouched.
- **`leads.phone` stores the RAW string.** Normalization happens only at the
  HubSpot boundary via `_crm_format_phone` (2469).
- Rule: nexus NEVER rewrites `leads.phone`. The E.164 form lives separately in
  `person_identity(channel='phone')` via `nexus.identity.normalize_phone`.
  Converging `_crm_format_phone` onto the nexus normalizer is a V2 cleanup,
  not V1.

## Stage-machine branches with NO hook (deliberate)

- TG triage offer set (3674–3683): an offer is not a pipeline stage; the
  opportunity opens at accept (C3). Avoids noise.
- Escape gates (3510 TG, 4047 IG) + retry-exhausted (3554, 4095): opportunity
  stays open; the 14-day staleness cron closes it as 'lost'. V1 keeps exits
  unwired.
- IG awaiting_qualification (3979): dead path in the current IG flow (cold
  entry jumps straight to awaiting_contact) — no hook.
- Crisis paths (3392 TG, 3950 IG): **no interaction logging, ever** — crisis
  content never becomes signal (M4 rule). Person creation via Hook A is fine;
  the content is not recorded in nexus tables.

## Webhook retry / duplication surfaces

| Surface | Behavior today | Nexus implication |
|---------|----------------|-------------------|
| Telegram retries | handler always returns 200 (even bad secret) → retries rare | hooks still idempotent by design |
| Telegram `edited_message` (3318) | an edited message is REPROCESSED as a new turn | funnel hooks must tolerate replays: leads unique index, one-open-opp index, forward-only stages, interaction dedup_key — all already hold |
| IG Meta redelivery | `_ig_seen_mids` (3704) in-process, 5-min TTL — resets on cold start, not shared across instances → duplicates possible TODAY | durable `interactions.dedup_key` is an improvement, not a regression; capture guarded by leads unique index |
| IG processing | `await run_in_threadpool(...)` completes BEFORE the 200 returns (3793) | post-response freeze is not a concern on this path |
| cron crm-sync (4261) | idempotent via `crm_synced_at IS NULL` | pattern to copy for memory-sweep |

**Idempotence invariant for every hook:** person_identity unique index,
one-open-opportunity partial index, forward-only stage machine, and
dedup_key on at-most-once interactions. A replayed webhook may at worst
re-log a harmless duplicate-free no-op.

## Out-of-scope findings recorded during the audit

1. **Web "Ask Erez" `/api/rag_query` (1893) is fully stateless** — no session,
   no message persistence, no capture path. Zero V1 wiring; web-channel recall
   is impossible until that endpoint persists sessions (V2 candidate).
2. `/api/chat` (1334) is the DataLens NL2SQL tool, not the coaching funnel —
   no hooks.
3. **bot_events is IG-only today**: Telegram captures never call `_track`
   (only `_audit`). The interactions log adds TG parity WITHOUT touching
   bot_events / analytics.funnel_daily — Power BI unaffected.
4. Schema drift: the live `sessions` table has `UNIQUE(channel, contact_id)`
   and `bot_state_expires_at`, neither present in the sql/ record files
   (applied historically via the management API). The nexus migrations DO have
   record files — keep it that way.
5. `_db_has_lead` (2208) keys on `(channel, chat_id)` — the per-channel-island
   dedup. It keeps working unchanged in V1; person-level "already a lead
   anywhere" checks become possible later via person_id but are NOT wired in
   V1 (behavior preservation).
