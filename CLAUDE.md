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

## 4. Cockpit design discipline — "Graphite Atelier" is the absolute source of truth (Sprint 5 guardrail)
The Cockpit's visual system is **"Graphite Atelier"** — a "quiet sanctuary that hides a
precision instrument": the calm, low-lit warmth of a private study fused with the razor-sharp
organization of a command center. Derived via the `ui-ux-pro-max` skill and locked by Erez
on 2026-06-20, it **permanently supersedes "Graphite Command"** (the cool-slate / electric-blue
skin) and the earlier buckssauce browns. References: Linear (typography, keyboard-first),
Notion dark (editorial negative space), an Aman-resort lounge at night (warm ambient light,
nothing screaming). Canonical tokens live in `fronted/src/cockpit/index.css` (`@theme`); every
component references the semantic Tailwind utilities only — `bg-bg`, `bg-surface`, `bg-raised`,
`text-ink`, `text-muted`, `text-faint`, `border-line`, `text-accent`, `text-sage`,
`text-success` / `text-warn` / `text-danger`, `font-serif` — never raw hex.

Primitives (warm obsidian, calibrated 2026-06-22): bg `#0c0907` · surface `#191310` · raised
`#231c15` · ink `#f2ebe0` (parchment) · muted `#a99c8c` · faint `#6f6357` · line parchment/16%
· accent `#c9aa71` (**champagne bronze — the one signature**, appears once with weight per view)
· sage `#8a9a82` (quiet supporting tone, live/calm cues, never competes with bronze) · success
`#7fa97f` · warn `#d8a657` · danger `#d08770` (warm — attention, never alarm). Radius 9 (controls)
/ 14 (cards).

**Shadow exception** (approved 2026-06-22 by Erez): `--shadow-card: 0 2px 12px rgba(0,0,0,0.40)`
— one ambient shadow for card surfaces only, applied via `[box-shadow:var(--shadow-card)]`. Never
decorative, never colored, never used outside `.rounded-card`. Creates the tactile "floating panel"
feel at sufficient bg-to-surface contrast; invisible to users consciously.

**Three typographic voices** — the signature risk, made structural (Machine vs. Human):
**Inter** for all UI / queue / system data (the Machine); **JetBrains Mono** `tabular-nums` for
every numeral — KPIs, counts, %, timestamps (the Instrument); **Fraunces** (light, soft optical)
for the Memory layer only — the emotional summary / core human problem (the Human). The sans stays
quiet; the serif speaks.

**Motion** — the whisper budget (CSS only, never a heavy anim lib; honors `prefers-reduced-motion`
via the global guard): the "one-thing" focus mechanic — on select, unselected queue rows recede
to 40% opacity (~260ms) while the thread + memory rise (`cq-rise`); the Human/Fraunces layer
recalls a touch slower (`cq-rise-slow`, ~420ms); the confidence bar draws once (`cq-grow`), never
loops; hover is color/opacity only, never scale.

Discipline: elevation via surface + border shifts first; `--shadow-card` permitted on card surfaces
(see approved exception above) — never decorative, never colored; no gradients; no blur; one
signature element, everything else quiet; sentence case; two weights. Apply real craft — never
templated or default-looking UI. When extending the system consult `ui-ux-pro-max`; adhere to this
aesthetic, don't drift.

---

Deep project history, locked decisions, and ops facts live in Claude's persistent
memory (the `MEMORY.md` index + its linked notes) — consult and update memory
rather than duplicating that context here.
