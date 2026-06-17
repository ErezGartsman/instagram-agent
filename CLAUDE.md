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

## 3. Bot voice — context-aware, never robotic (Sprint 5 guardrail)
The WhatsApp funnel must NOT fire the psychological opener on a bare greeting
("hi", "היי"). Initiate the funnel only on clear intent (or after a delay); on a
bare greeting, stay silent or send an ultra-brief, human acknowledgment. The bot
is a person, not a tripwire.

## 4. Cockpit design discipline — studio-level, never "AI-generated" (Sprint 5 guardrail)
Every Cockpit component adheres to Erez's design system (`skillui` + `DESIGN.md`
tokens) with strict discipline on typography, spacing, and restraint. No templated
or default-looking UI. Use the provided tokens exactly; apply real design craft
(one signature element, everything else quiet). Erez supplies the tokens/patterns
per component — adhere, don't improvise.

---

Deep project history, locked decisions, and ops facts live in Claude's persistent
memory (the `MEMORY.md` index + its linked notes) — consult and update memory
rather than duplicating that context here.
