# One Thread — PRD & Tech Spec

**Status:** Approved 2026-07-09 · **Roadmap position:** Feature 1 of 3 (Flows, Signal follow)
**North star:** time-to-booked-consultation

---

## 0. Where we are today (grounded)

| Piece | Current state | Reused by One Thread |
|---|---|---|
| Thread read | `_db_whatsapp_thread()` merges `messages` (inbound bodies) + `outbound_messages` (our replies), **WhatsApp only** | Generalize to all channels |
| Identity | `person_identity(channel, external_id, username)`, `UNIQUE(channel, external_id)`; channels: instagram/telegram/whatsapp/phone/email/web | The routing backbone |
| Send primitives | `_kapso_call` (WA), `_send_telegram_message` (TG), IG graph send | Wrapped behind one adapter |
| "Send" from cockpit | Doesn't exist — `/whatsapp/outreach` only logs an `outreach_click`; Erez sends manually via `wa.me` | Replaced by a real send endpoint |
| Draft | `/whatsapp/draft` → Copilot draft + phone, returns text for `wa.me` | Feeds the composer, approval-gated |
| UI | `WhatsAppThread.tsx` — read-only glass bubbles (`user`/`assistant`/`operator`), RTL, Midnight tokens, no composer | Evolves into `ConversationThread.tsx` |

**Gap:** thread is single-channel and read-only; sending is manual off-platform.

## 1. Objectives & non-goals

**Objectives:** one chronological conversation per `person` across WA/IG/TG; reliable send-from-cockpit with correct channel routing; window-aware deliverability; full audit trail; zero new nav clutter.

**Non-goals (locks respected):** does not revive the retired qualification funnel; no auto-send (human presses Send — consistent with Copilot "drafts, never auto-send" and the intake-assistant lock: the bot stays silent, the human consults); crisis gate untouched; multi-tenancy stays deferred (`tenant_id` stays the constant); media/group send = V2.

## 2. The PII policy decision

The V1 "inbound bodies out-of-system" rule is already superseded for WhatsApp: inbound bodies persist in `messages` and render in the WS1 thread today ("Option B — sensitive data visible inside the cockpit"). One Thread's only new PII surface is rendering IG/Telegram inbound bodies the same way.

**Decision (locked 2026-07-09): all channels.** Posture stays identical across channels: bodies live only in `messages` / `outbound_messages` (RLS deny-all, backend-only via postgres); `interactions.payload` stays ref-only; every send is stamped with the operator email.

---

## 3. Data Contract

### 3.1 Unified read model — `ThreadMessage`

```jsonc
{
  "id":        "om_… | msg_…",
  "channel":   "whatsapp|instagram|telegram",
  "direction": "in | out",
  "role":      "user | assistant | operator",
  "body":      "verbatim text",
  "at":        "ISO-8601",
  "status":    "sent|delivered|read|failed|null",
  "provider_message_id": "wamid…|null"
}
```

Backend: generalize `_db_whatsapp_thread` → `_db_person_thread(conn, person_id, channels=None)`:
- Inbound = `messages m JOIN sessions s ON s.id=m.session_id WHERE s.person_id=%s` — drop the `s.channel='whatsapp'` filter; take `channel` from `s.channel`.
- Outbound = `outbound_messages WHERE person_id=%s` — take `channel` from the column.
- Merge oldest-first (unchanged logic).

### 3.2 Outbound write model — additive migration `008_outbound_messages_delivery.sql`

`outbound_messages` exists but is WhatsApp-shaped and has no delivery state. Additive only:

| Column | Type | Why |
|---|---|---|
| `status` | `TEXT NOT NULL DEFAULT 'sent'` | queued→sent→delivered→read→failed lifecycle |
| `failure_reason` | `TEXT` | surface provider errors in the UI |
| `provider` | `TEXT` | `kapso` / `meta_ig` / `telegram` — audit which rail fired |
| `send_target` | `TEXT` | exact address sent to (phone/igsid/chat_id) — audit + debugging |
| `client_token` | `TEXT` + partial `UNIQUE` | idempotency: double-click / retry can't double-send |

`channel` stops relying on the `'whatsapp'` default going forward — callers pass it explicitly (column kept for back-compat). Existing `(person_id, sent_at DESC)` index already covers the thread read.

### 3.3 Identity linkage

Every message hangs off canonical `person_id`. The send address is resolved from `person_identity(channel, external_id)` — never stored on the person. Contract: `resolve_send_target(person_id, channel) → (external_id, username) | None`.

---

## 4. Outbound Routing

### 4.1 Channel resolution order (deterministic)

1. **Explicit** — operator picked a channel in the composer. Must have a matching `person_identity`; if not, block with a fix-it.
2. **Reply-to-last-inbound** *(locked default 2026-07-09)* — channel of the person's most recent inbound message.
3. **Origin** — `opportunities.source_channel`, else earliest `person_identity`.

### 4.2 Send-eligibility windows

| Channel | Free-form rule | Outside window |
|---|---|---|
| WhatsApp | ≤ 24h since last inbound (service window) | Block → approved template only (V2) |
| Instagram | ≤ 24h standard; human-agent tag extends to 7d | Block with reason |
| Telegram | Open once the user has started the bot | Always eligible |

Computed from the latest inbound `messages.created_at` for that `(person, channel)`. The thread endpoint returns per-channel eligibility so the UI can enable/disable and explain.

### 4.3 The adapter seam

```
ChannelSender.send(target, body) -> { provider_message_id, provider }
  whatsapp  -> _kapso_call(...)
  telegram  -> _send_telegram_message(chat_id, body)
  instagram -> _ig_send(igsid, body)
```

`route_and_send(person_id, channel|None, body, operator_email, client_token)`:
1. resolve channel (4.1) + target (`person_identity`)
2. check eligibility (4.2) → reject with `reason_code` if blocked
3. call adapter
4. success → INSERT `outbound_messages` (status `sent`, `provider_message_id`, `provider`, `sent_by`, `client_token`) + `log_interaction(kind='contacted', channel, ref-only)` + reset the SLA clock
5. failure → INSERT `outbound_messages` (status `failed`, `failure_reason`), return error

Delivery/read receipts (V2): inbound webhooks already receive Kapso/Meta status callbacks → `UPDATE outbound_messages.status` by `provider_message_id`. Column designed now, wired later.

### 4.4 API surface

| Method | Route | Body → Response |
|---|---|---|
| GET | `/api/cockpit/thread/{person_id}` *(extended)* | → `{ messages[], channels: {whatsapp:{eligible,reason,window_expires_at}, …}, default_channel }` |
| POST | `/api/cockpit/thread/{person_id}/send` *(new)* | `{ channel?, body, client_token }` → `{ status, message } \| { status:'error', reason_code, detail }` |
| — | `/api/cockpit/whatsapp/draft` *(kept)* | feeds the composer's "Draft with Copilot" |
| — | `/api/cockpit/whatsapp/outreach` *(kept as fallback)* | assisted `wa.me` when send is ineligible |

All `require_cockpit_user`.

---

## 5. UI/UX Component

Principle: no new nav, no new page. The thread already lives in the Person Dossier center pane. We change one component in place.

### 5.1 `WhatsAppThread.tsx` → `ConversationThread.tsx`

Keep the bubble system exactly (glass inbound / accent operator / centered handoff ACK, RTL `dir="auto"`, `cq-rise`, mono timestamps). Additive changes:
- **Channel chip** on inbound bubbles — a tiny mono label (`WA`/`IG`/`TG`) only when the person spans >1 channel; hidden otherwise.
- **Composer** docked at the bottom (Phase 2+).
- **Channel selector** shown only when multiple identities exist.

### 5.2 The composer (Phase 2+)

Textarea (`dir="auto"`), a channel pill (auto-resolved via 4.1; click to change; ineligible channels greyed with a tooltip reason), a ghost "Draft with Copilot" button, and Send. States: window-open / window-closed (+ reason) / no-address (inline fix-it). Optimistic append with a status pill. Midnight tokens only; sub-300ms motion.

### 5.3 Placement & reflow

Center pane of `PersonDossierPage`; reflows through `aiDock` when pinned (never overlays data). Later: ⌘K "Message {name}" focuses the composer.

---

## 6. Rollout (flag-gated via `FEATURES.oneThread`)

| Phase | Ships | Risk |
|---|---|---|
| **1 — Read** | Multi-channel thread (backend query + component rename + channel chips) | None (read-only) |
| **2 — Send (WA)** | `008` migration + adapter + POST send + composer, WhatsApp 24h window only | Low, dogfood |
| **3 — Multi-send** | Telegram + IG adapters + eligibility UI | Medium (IG window/tag) |
| **4 — Receipts** | delivery/read status from webhooks | V2 |

## 7. Risks → mitigations

Sending outside window → eligibility gate. Wrong-channel send → require resolvable identity + show target address in composer. Double-send → `client_token`. Scope creep into a bot → send is human-only, funnel stays retired. PII widening → same RLS/backend-only posture (§2).

## 8. Success metrics

Inbound→first-reply latency ↓ · % replies sent in-cockpit vs phone ↑ · send-failure rate < 2% — all bending the north star, time-to-booked-consultation.
