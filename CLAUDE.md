# NEXUS — Project Instructions

Standing rules for Claude in this repository. These OVERRIDE default behavior and
must survive every context compaction. Read them at the start of every session.

## 1. The Golden Rule — always address Erez by name
Begin **every** response to the user with his name, "Erez"
(e.g., "Erez, I've built…", "Erez, here are the steps…"). No exceptions, every turn.

## 2. Roadmap alignment — the next milestone is "The Cockpit"
The shipped milestone is the WhatsApp qualification funnel (Sprint 4). The **next
major milestone is Sprint 5: "The Cockpit"** — a comprehensive command center /
dashboard to manage all leads and conversations in one place. It begins once the
real number (0546150955) is stable in production. Keep proposals and architecture
decisions pointed at that north star.

## 3. WhatsApp bot — intake assistant, NOT a counselor (LOCKED, Ticket 4.6)
Pivoted 2026-06-21 after the funnel sent generic "therapist" advice to emotionally
heavy messages and killed leads. The WhatsApp bot's OUTWARD persona is strictly an
intake assistant / clinic manager. **Absolute rule:** on first contact it sends
exactly ONE fully transparent automated handoff message (`whatsapp.handoff_ack` —
"this is automated… Erez reads and replies personally"), then goes COMPLETELY
SILENT. Zero conversational looping, zero AI advice/insights/qualification. The
old qualification funnel (`_wa_run_qualification`, opener/insight/price/booking) is
RETIRED — kept in code for rollback only; do not re-wire without an explicit
decision to reverse this pivot.

**Inward, the brain keeps running silently:** inbound messages are still persisted,
the opportunity is still opened (so the person lands in the Work Queue), and the
daily formation cron still builds the Person-360 (goal / tension / essence). The
Machine organizes the data; the Human (Erez) does the actual consulting.

**Safety exception:** the crisis gate (`is_crisis` → `crisis.message`) ALWAYS fires,
upstream of everything — never silence a self-harm signal.

## 4. Cockpit design discipline — Neon Glassmorphism Engine (pivoted 2026-06-22)
Graphite Atelier (warm obsidian / champagne bronze) is **retired**. The new system
is the **Neon Glassmorphism Engine**, pivoted on Erez's directive 2026-06-22.
References: Dealstack (violet glassmorphism CRM), G.Take (deep navy glass cards),
21st.dev component library aesthetic.

**Three-layer depth architecture — never collapse any layer:**
1. **Void + dual ambient glow** — CSS radial gradients on `.cockpit-root`: violet
   crown top (`rgba(109,40,217,0.35)`) + electric-blue depth bottom-right
   (`rgba(59,130,246,0.22)`) + secondary violet bottom-left (`rgba(109,40,217,0.12)`)
   over `#060012` void base. No images, no canvas — pure CSS.
2. **Glass panels** — `bg-surface` (`rgba(255,255,255,0.08)`) + `backdrop-blur-xl`
   on section-level containers: Sidebar, Topbar, StatCard, feature cards.
   **Never on list rows** (GPU cost). List rows get `bg-surface` rgba only.
3. **Neon signatures** — `--color-accent: #7c3aed` (violet-700) for fills/badges;
   `--color-glow: #a78bfa` (violet-400) for pip glow, confidence %, gradient tips.
   One neon `box-shadow` per active element only — never decorative.

Canonical tokens in `fronted/src/cockpit/index.css` (`@theme`). Semantic utilities
only — `bg-surface`, `bg-raised`, `text-ink`, `text-muted`, `text-faint`,
`border-line`, `text-accent`, `text-glow`, `text-sage`, `text-success` / `text-warn`
/ `text-danger` — never raw hex in components.

**Primitives (neon void, 2026-06-22):** bg `#060012` · surface `rgba(255,255,255,0.08)`
glass · raised `rgba(255,255,255,0.12)` hover glass · ink `#ffffff` · muted `#a1a1aa` ·
faint `#52525b` · line `rgba(255,255,255,0.08)` · accent `#7c3aed` · glow `#a78bfa` ·
sage `#60a5fa` (electric blue) · success `#7fa97f` · warn `#d8a657` · danger `#d08770`.
Radius 9px (controls) / 14px (cards).

**Elevation:** `--shadow-card: 0 0 24px rgba(124,58,237,0.20), inset 0 1px 0 rgba(255,255,255,0.08)`
on glass cards. `--shadow-glow: 0 0 8px rgba(167,139,250,0.90), 0 0 16px rgba(124,58,237,0.50)`
for the active nav pip. No flat black shadows — glow-based only.

**Typography — two voices (the logic machine):**
**Inter** for all UI. **JetBrains Mono** `tabular-nums` for every numeral.
**Fraunces** is reserved for the Overview `greeting()` heading ONLY — `font-serif` on
that one `<h2>` — and **nowhere else in the cockpit**. It is "the human voice in the
machine" per Erez's decision. Enforce strictly; reject any other `font-serif` usage.

**Framer Motion** — in bundle. `StatCard` uses stagger entrance (`delay: index * 0.08s`)
with `useReducedMotion()` guard. Never continuous/looping — `cq-grow` is the only
draw-once CSS exception.

**Motion whisper budget** (CSS): `cq-rise` 0.26s · `cq-rise-slow` 0.42s · `cq-grow`
0.7s. All killed by global `prefers-reduced-motion` guard in `index.css`.

Discipline: glass over void always. Backdrop-blur on section containers only. Neon
glow on active states only. No warm tones anywhere. Sentence case; two weights max.
When extending, consult `ui-ux-pro-max`; never drift back toward warm/flat.

---

Deep project history, locked decisions, and ops facts live in Claude's persistent
memory (the `MEMORY.md` index + its linked notes) — consult and update memory
rather than duplicating that context here.
