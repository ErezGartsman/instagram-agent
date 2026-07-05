# Fable build notes — cockpit AI query planner (2026-07-05)

Lessons from replacing the `_ACTION_CHIP_MAP` chip router with the
`nexus/ai_planner.py` tool-use planner. One lesson per entry, with why it
mattered. Update entries in place rather than duplicating.

## 1. The tunnel-vision bug was structural, not a tuning problem
The old router matched `msg.lower()` against ~25 exact strings. Any phrasing
variation (Hebrew, typos, "show me the pipeline") produced zero chips → zero
context blocks → the LLM answered a data question with no data and improvised.
**Why it matters:** any hardcoded phrasing list decays as the UI grows. The fix
is semantic (the model maps *meaning* → tool), while everything the UI renders
stays deterministic. Never route by exact strings again; extend the registry.

## 2. The frozen contract survives model swaps because the model never touches it
`intent`, `context_data`, and `actions` are assembled in Python from SQL rows
(`ToolResult` builders + `resolve_contract`). The LLM only (a) picks tool names
+ typed args, (b) writes prose. **Why:** this is what makes the endpoint safe on
Gemini 2.5 Flash, Opus, or anything else — a weaker model can pick a wrong tool
(bad answer) but can never emit a malformed widget payload, an invented phone
number in `context_data`, or an out-of-enum intent (`resolve_contract` drops
unknown intents to "general").

## 3. Plan-over-prompt beats native function calling here
`_call_llm` is a plain-text seam. The planner asks for strict JSON
(`{"plan":[{"tool","args"}]}`), parsed by the existing `_parse_llm_json` repair
pipeline, validated by `parse_plan`/`validate_args`. **Why:** zero dependency on
any provider's tool-use API = model-agnostic by construction. Any parse or
validation failure falls back to the legacy router (`_legacy_ai_chat_context`),
so the endpoint cannot go dark. Kill switch: `app_config
ai_chat.planner_enabled = "false"`.

## 4. Tenancy is a seeded constant, not a JWT claim — inject it server-side
`require_cockpit_user` returns Supabase claims with no tenant. Migration
v1_001 seeds tenant `00000000-…-0001` on every root table. So
`_execute_ai_plan` passes `ai_planner.DEFAULT_TENANT_ID` into every tool; the
plan JSON cannot supply or omit it. **Why:** isolation must not depend on the
model behaving. Note the schema's real boundary: social tables
(posts/likers/comments/followers), sessions/messages, sla_config,
funnel_metrics have NO tenant column — sessions/messages are scoped through the
person join; the rest are single-tenant by schema (documented per-tool).

## 5. Don't reuse `nexus_reader` for the planner — wrong layer
The existing raw-SQL guard drops to the `nexus_reader` role, which only grants
the social tables and would block person/opportunities/SLA. The planner needs
those, and its SQL is ours + parameter-bound, so the right defense-in-depth is
just `SAVEPOINT` + `SET LOCAL transaction_read_only = on` (Postgres rejects any
write), with per-step savepoints so one failing tool doesn't poison the
transaction for later steps, and a `finally` rollback that leaves the pooled
connection clean.

## 6. Cheap structural test invariants catch what review misses
The harness asserts, for every tool run: (a) every SQL touching a
tenant-bearing table binds `%(t)s = DEFAULT_TENANT_ID`, (b) every
row-returning SQL contains LIMIT, (c) `context_data` key sets exactly match the
TSX widget casts. Invariant (b) immediately caught two unbounded GROUP BY
aggregates. **Why:** these run on every future registry entry automatically —
the constraint is enforced forever, not reviewed once.

## 7. Local test failures that aren't yours: prove it, don't assume it
`tests/test_main.py` shows 25 failures locally (401s — cockpit auth env not
configured for those older tests) and `test_cockpit_copilot_endpoints.py` shows
1 (local `.env` sets `copilot_demo_mock=True`, so the stream test gets the demo
draft instead of the mocked LLM). Verified byte-identical failure sets with and
without the planner change by restoring clean `main.py` and diffing `FAILED`
lists. **Why:** "pre-existing" is a claim that needs evidence; the diff is the
evidence. Also: `git stash push <pathspec>` silently can't stash untracked
files — copy-to-scratchpad + `git checkout --` is the deterministic way.

## 8. A fresh-context verifier catches what the builder's context hides
A subagent auditing the finished code with no build context found: (a) the
empty-input early return — preserved verbatim from the OLD endpoint — returned
only `{status, reply}`, violating the five-key frozen contract on one path;
(b) the legacy fallback's `f"sla_lead_{row[5]}"` could leak an out-of-enum
intent on an unexpected `sla_status`; (c) my str-arg cleaner replaced `_` with
a space, silently breaking lookups of underscored ref codes (`lead_42`).
All three fixed + pinned by tests. **Why:** "preserved from the original" is
not the same as "meets the constraint" — the builder inherits the original's
blind spots along with its code. Audit finished work against the constraint
list, not against the diff.

## 9. Sensitive data policy is directional, not global (Erez, 2026-07-05)
The `session_summaries.sensitive` flag gates OUTWARD channels (WhatsApp bot),
not the private cockpit. Ratified Option B: `person_360` shows everything,
tagged `[sensitive]`, rendered as plain `general` text — no new widget, no
contract change. **Why:** encoding this as "hide sensitive everywhere" would
have crippled the operator's own Person-360 view; the boundary is the channel,
not the data.
