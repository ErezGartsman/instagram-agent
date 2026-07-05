"""
nexus.ai_planner — model-agnostic query planner behind the cockpit AI chat.

Replaces the hardcoded chip router (_ACTION_CHIP_MAP + if/elif chip parser) in
POST /api/cockpit/ai/chat with a tool-use loop that any instruction-following
LLM can drive:

    1. build_planner_prompt()  — the LLM sees a catalog of read-only data tools
                                 and returns a strict-JSON plan (never SQL).
    2. parse_plan()            — defensive parse + typed arg validation. Any
                                 structural failure raises PlanError, which the
                                 endpoint treats as "fall back to the legacy
                                 router" — the endpoint can never go dark.
    3. run_tool()              — executes one validated step against a cursor
                                 the endpoint provides (inside a read-only
                                 transaction). All SQL lives HERE, is
                                 parameter-bound, tenant-scoped, and LIMIT'd.
    4. build_reply_prompt()    — grounded synthesis prompt: the reply LLM may
                                 only use the fetched blocks, and must say so
                                 honestly when nothing was fetched.

Security posture (by construction, not by convention):
  • The model chooses tool NAMES and typed ARGS only — SQL strings are fixed
    module constants with %(name)s placeholders; args are validated (enum /
    length / int-clamp) before binding, and psycopg2 binding makes injection
    structurally impossible.
  • tenant_id is injected by the ENDPOINT (server-side constant), never read
    from the plan. Tables without a tenant_id column (the social tables,
    sessions/messages, funnel_metrics) are single-tenant by schema — noted
    per-tool below.
  • intent / context_data / actions — the frozen frontend contract rendered by
    GlowingAiAssistant.tsx — are assembled deterministically in Python from
    SQL rows. The LLM never touches them.

Like nexus.copilot / nexus.work_queue this module owns no connection and no
LLM client: the endpoint gathers those, this module decides. That keeps every
layer unit-testable with the LLM and DB mocked (tests/test_ai_planner.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# Single seeded tenant (migration v1_001) — the only tenant that exists today.
# The endpoint passes this to run_tool(); a future multi-tenant cockpit swaps
# the constant for a per-user lookup without touching any tool SQL.
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Hard bounds — keep any model (Flash or Opus) inside a predictable budget.
MAX_TOOLS_PER_PLAN = 4
MAX_ARG_STR_LEN = 60
HISTORY_TURNS = 6

# Pipeline stages in funnel order — the only values stage args may take.
PIPELINE_STAGES = ("engaged", "qualified", "captured", "briefed", "booked")

# The frozen intent enum. GlowingAiAssistant.tsx renders widgets for
# sla_lead_* / sla_overview / funnel / velocity / post / top_posts / community;
# growth / pipeline / general are valid intents without a widget. Do not add
# values here without shipping a frontend renderer first.
FROZEN_INTENTS = frozenset(
    {
        "sla_lead_breach", "sla_lead_warn", "sla_lead_ok", "sla_lead",
        "sla_overview", "funnel", "velocity", "pipeline",
        "post", "top_posts", "community", "growth", "general",
    }
)

_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")


class PlanError(ValueError):
    """The plan is structurally unusable → endpoint falls back to legacy router."""


# ── Arg validation ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArgSpec:
    kind: str                      # "enum" | "str" | "int" | "shortcode"
    required: bool = False
    choices: tuple = ()            # kind == "enum"
    max_len: int = MAX_ARG_STR_LEN # kind == "str"
    min_val: int = 1               # kind == "int"
    max_val: int = 15
    default: Any = None


def _clean_arg(name: str, spec: ArgSpec, raw: Any) -> Any:
    """Coerce one raw arg to its validated form, or raise PlanError."""
    if raw is None:
        if spec.required:
            raise PlanError(f"missing required arg '{name}'")
        return spec.default

    if spec.kind == "enum":
        val = str(raw).strip().lower()
        if val not in spec.choices:
            raise PlanError(f"arg '{name}'={raw!r} not in {spec.choices}")
        return val

    if spec.kind == "int":
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise PlanError(f"arg '{name}'={raw!r} is not an int")
        return max(spec.min_val, min(spec.max_val, val))

    if spec.kind == "shortcode":
        val = str(raw).strip().strip("·!,.")
        if not _SHORTCODE_RE.match(val):
            raise PlanError(f"arg '{name}'={raw!r} is not a valid shortcode")
        return val

    # kind == "str" — free text (person-name fragments). Binding makes SQL
    # injection impossible; we still strip the % LIKE wildcard so a hostile
    # value can't widen a pattern match, and cap length. Underscores are KEPT:
    # ref codes / usernames contain them, and as a LIKE single-char wildcard
    # an underscore still matches itself (benign, and always bound).
    val = str(raw).strip().replace("%", "")
    return val[: spec.max_len] or (spec.default if not spec.required else None)


def validate_args(tool: "Tool", raw_args: Any) -> dict:
    """Validate a raw args mapping against the tool's spec. Unknown keys dropped."""
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, dict):
        raise PlanError(f"args for '{tool.name}' is not an object")
    clean: dict = {}
    for name, spec in tool.args.items():
        clean[name] = _clean_arg(name, spec, raw_args.get(name))
        if spec.required and clean[name] in (None, ""):
            raise PlanError(f"missing required arg '{name}' for '{tool.name}'")
    return clean


# ── Tool plumbing ──────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """One executed step: a prompt block + (optionally) frozen-contract fields."""
    tool: str
    context_block: str
    intent: str | None = None       # None → does not claim the primary intent
    ctx_data: dict | None = None    # deterministic widget payload (frozen shape)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str                                   # one line, shown to the planner
    run: Callable[..., ToolResult]                     # (cur, tenant_id, get_config, args)
    args: dict[str, ArgSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanStep:
    tool: str
    args: dict


def _rows(cur, sql: str, params: dict | None = None) -> list:
    cur.execute(sql, params or {})
    return cur.fetchall()


def _one(cur, sql: str, params: dict | None = None):
    cur.execute(sql, params or {})
    return cur.fetchone()


def _lead_name_sql(alias: str = "p") -> str:
    return f"COALESCE({alias}.display_name, 'Lead '||{alias}.wa_ref_code, 'Lead')"


def _like(frag: str) -> str:
    return f"%{frag.lower()}%"


# ── Tools — analytics domains (mirror the legacy router's queries + shapes) ───

def _t_funnel_overview(cur, tenant_id, get_config, args) -> ToolResult:
    fm_rows = _rows(cur,
        "SELECT from_stage, to_stage, unique_leads, conversion_pct, avg_hours_in_stage "
        "FROM funnel_metrics ORDER BY from_stage, to_stage LIMIT 50")
    stage_counts = dict(_rows(cur,
        "SELECT stage, COUNT(*) FROM opportunities "
        "WHERE closed_at IS NULL AND tenant_id = %(t)s GROUP BY stage LIMIT 10",
        {"t": tenant_id}))
    total_leads = _one(cur,
        "SELECT COUNT(DISTINCT person_id) FROM opportunities WHERE tenant_id = %(t)s",
        {"t": tenant_id})[0]

    lines = []
    for r in fm_rows:
        pct = f"{r[3]}%" if r[3] is not None else "—"
        vel = f"{r[4]}h avg time" if r[4] is not None else "velocity unknown"
        lines.append(f"  {r[0]} → {r[1]}: {r[2]} leads  {pct} conversion  {vel}")
    open_str = "  |  ".join(f"{k}: {v}" for k, v in sorted(stage_counts.items())) or "no open leads"
    block = (f"PIPELINE FUNNEL ({total_leads} total leads):\n" + "\n".join(lines) +
             f"\n\n  CURRENT OPEN LEADS: {open_str}")

    stages_widget = []
    for sn in PIPELINE_STAGES:
        pair = next((r for r in fm_rows if r[0] == sn), None)
        stages_widget.append({
            "stage": sn,
            "count": stage_counts.get(sn, 0),
            "conv_pct": float(pair[3]) if pair and pair[3] is not None else None,
        })
    return ToolResult("funnel_overview", block, "funnel",
                      {"type": "funnel", "total_leads": total_leads, "stages": stages_widget})


def _t_stage_pipeline(cur, tenant_id, get_config, args) -> ToolResult:
    sn = args["stage"]
    row = _one(cur,
        "SELECT COUNT(*), "
        "       ROUND(AVG(EXTRACT(EPOCH FROM (NOW()-stage_entered_at))/3600),1) "
        "FROM opportunities WHERE stage = %(s)s AND closed_at IS NULL AND tenant_id = %(t)s",
        {"s": sn, "t": tenant_id})
    avg_h = f"  |  avg {row[1]}h in stage" if row[1] else ""
    return ToolResult("stage_pipeline",
                      f"STAGE '{sn.upper()}': {row[0]} open leads{avg_h}",
                      "pipeline",
                      {"type": "pipeline", "stage": sn, "count": row[0],
                       "avg_hours": float(row[1]) if row[1] is not None else None})


def _t_stage_velocity(cur, tenant_id, get_config, args) -> ToolResult:
    sn = args.get("stage")
    if sn:
        row = _one(cur,
            "SELECT avg_hours_in_stage, median_hours_in_stage, conversion_pct "
            "FROM funnel_metrics WHERE from_stage = %(s)s LIMIT 1", {"s": sn})
        if row and row[0] is not None:
            block = (f"VELOCITY — {sn.upper()}:\n"
                     f"  Avg time before advancing: {row[0]}h\n"
                     f"  Median: {row[1]}h  |  Conversion: {row[2]}%")
            return ToolResult("stage_velocity", block, "velocity", {
                "type": "velocity", "stage": sn,
                "avg_hours": float(row[0]),
                "median_hours": float(row[1]) if row[1] is not None else None,
                "conv_pct": float(row[2]) if row[2] is not None else None,
            })
        return ToolResult("stage_velocity",
                          f"VELOCITY — {sn.upper()}: no data yet "
                          f"(leads haven't advanced from this stage)", "velocity")
    rows = _rows(cur,
        "SELECT from_stage, avg_hours_in_stage, conversion_pct "
        "FROM funnel_metrics WHERE avg_hours_in_stage IS NOT NULL "
        "ORDER BY from_stage LIMIT 20")
    lines = [f"  {r[0]}: avg {r[1]}h, {r[2]}% conversion" for r in rows]
    return ToolResult("stage_velocity",
                      "STAGE VELOCITY (all stages):\n" +
                      ("\n".join(lines) if lines else "  No velocity data yet"),
                      "velocity")


def _t_sla_overview(cur, tenant_id, get_config, args) -> ToolResult:
    counts = dict(_rows(cur,
        "SELECT s.sla_status, COUNT(*) FROM lead_sla_status s "
        "JOIN person p ON p.id = s.person_id AND p.tenant_id = %(t)s "
        "GROUP BY s.sla_status LIMIT 10", {"t": tenant_id}))
    top = _rows(cur,
        "SELECT s.person_id, COALESCE(s.person_name,'Lead '||p.wa_ref_code,'Lead'), "
        "       s.stage, s.hours_in_stage, s.target_hours, s.sla_status "
        "FROM lead_sla_status s "
        "JOIN person p ON p.id = s.person_id AND p.tenant_id = %(t)s "
        "ORDER BY CASE s.sla_status WHEN 'breach' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, "
        "         s.hours_in_stage DESC NULLS LAST LIMIT 5", {"t": tenant_id})
    wa_phones = {str(r[0]): r[1] for r in _rows(cur,
        "SELECT s3.person_id, pi.external_id FROM lead_sla_status s3 "
        "JOIN person p3 ON p3.id = s3.person_id AND p3.tenant_id = %(t)s "
        "JOIN person_identity pi ON pi.person_id = s3.person_id "
        "  AND pi.channel = 'whatsapp' LIMIT 20", {"t": tenant_id})}

    top_lines = [f"  {r[1]}: {r[2]} · {r[3]}h/{r[4]}h · {r[5].upper()}" for r in top]
    block = (f"SLA OVERVIEW:\n"
             f"  Breached: {counts.get('breach', 0)}  "
             f"At risk: {counts.get('warn', 0)}  "
             f"On track: {counts.get('ok', 0)}\n"
             f"TOP LEADS BY URGENCY:\n" + "\n".join(top_lines))
    ctx = {
        "type": "sla_overview",
        "counts": {k: v for k, v in counts.items()},
        "top_leads": [
            {
                "person_id": str(r[0]), "name": r[1], "stage": r[2],
                "hours_in_stage": float(r[3]) if r[3] is not None else 0,
                "target_hours": r[4], "sla_status": r[5],
                "wa_phone": wa_phones.get(str(r[0])),
            }
            for r in top
        ],
    }
    return ToolResult("sla_overview", block, "sla_overview", ctx)


def _t_sla_lead_lookup(cur, tenant_id, get_config, args) -> ToolResult:
    frag = _like(args["name"])
    row = _one(cur,
        "SELECT COALESCE(s.person_name,'Lead '||p.wa_ref_code,'Lead'), "
        "       s.stage, s.hours_in_stage, s.target_hours, "
        "       s.warn_hours, s.sla_status, s.person_id "
        "FROM lead_sla_status s "
        "JOIN person p ON p.id = s.person_id AND p.tenant_id = %(t)s "
        "WHERE lower(COALESCE(s.person_name,'')) LIKE %(f)s "
        "   OR lower(COALESCE(p.wa_ref_code,'')) LIKE %(f)s "
        "LIMIT 1", {"t": tenant_id, "f": frag})
    if not row:
        return ToolResult("sla_lead_lookup",
                          f"LEAD CONTEXT: {args['name']}  (no matching open lead — "
                          f"the person may be closed/snoozed or the name misspelled)")
    ph = _one(cur,
        "SELECT external_id FROM person_identity "
        "WHERE person_id = %(p)s AND channel = 'whatsapp' LIMIT 1", {"p": row[6]})
    block = (f"LEAD — {row[0]}:\n"
             f"  Stage: {row[1]}  |  Hours in stage: {row[2]}h  "
             f"|  SLA target: {row[3]}h  |  Warn at: {row[4]}h  "
             f"|  Status: {row[5].upper()}")
    intent = f"sla_lead_{row[5]}"
    if intent not in FROZEN_INTENTS:            # unexpected status value → base intent
        intent = "sla_lead"
    return ToolResult("sla_lead_lookup", block, intent, {
        "type": "sla_lead", "name": row[0], "stage": row[1],
        "hours_in_stage": float(row[2]) if row[2] is not None else 0,
        "target_hours": row[3], "warn_hours": row[4], "sla_status": row[5],
        "person_id": str(row[6]) if row[6] else None,
        "wa_phone": ph[0] if ph else None,
    })


def _t_community_metrics(cur, tenant_id, get_config, args) -> ToolResult:
    # Social tables carry no tenant_id (single-tenant by schema).
    community_size = int(get_config("analytics.community_size") or 0)
    total_likes = _one(cur, "SELECT COUNT(*) FROM likers")[0]
    total_comments = _one(cur, "SELECT COUNT(*) FROM comments")[0]
    total_posts = _one(cur, "SELECT COUNT(*) FROM posts")[0]
    block = (f"COMMUNITY METRICS:\n"
             f"  Total community size: {community_size:,}\n"
             f"  Total tracked likes:  {total_likes:,}\n"
             f"  Total comments:       {total_comments:,}\n"
             f"  Total posts tracked:  {total_posts:,}")
    return ToolResult("community_metrics", block, "community", {
        "type": "community", "community_size": community_size,
        "total_likes": total_likes, "total_comments": total_comments,
        "total_posts": total_posts,
    })


def _t_follower_growth(cur, tenant_id, get_config, args) -> ToolResult:
    community_size = int(get_config("analytics.community_size") or 0)
    rows = _rows(cur,
        "SELECT to_char(date_trunc('week', followed_at), 'YYYY-MM-DD'), COUNT(*) "
        "FROM followers WHERE followed_at IS NOT NULL "
        "GROUP BY 1 ORDER BY 1 DESC LIMIT 8")
    weekly = [{"week": wk, "new_followers": n} for wk, n in reversed(rows)]
    lines = [f"  {w['week']}: +{w['new_followers']} new followers" for w in weekly]
    block = (f"FOLLOWER GROWTH (community total: {community_size:,}):\n" +
             ("\n".join(lines) if lines else "  No weekly data available"))
    return ToolResult("follower_growth", block, "growth",
                      {"type": "growth", "community_size": community_size, "weekly": weekly})


def _t_top_posts(cur, tenant_id, get_config, args) -> ToolResult:
    top = _rows(cur,
        "WITH lk AS (SELECT post_shortcode, COUNT(*) c FROM likers GROUP BY 1), "
        "     cm AS (SELECT post_shortcode, COUNT(*) c FROM comments GROUP BY 1) "
        "SELECT p.post_shortcode, COALESCE(lk.c,0), COALESCE(cm.c,0) "
        "FROM posts p "
        "LEFT JOIN lk ON lk.post_shortcode = p.post_shortcode "
        "LEFT JOIN cm ON cm.post_shortcode = p.post_shortcode "
        "ORDER BY COALESCE(lk.c,0) DESC LIMIT %(n)s", {"n": args["limit"]})
    lines = [f"  #{i + 1} {r[0]}: {r[1]:,} likes, {r[2]:,} comments" for i, r in enumerate(top)]
    return ToolResult("top_posts", "TOP POSTS BY LIKES:\n" + "\n".join(lines), "top_posts", {
        "type": "top_posts",
        "posts": [{"shortcode": r[0], "likes": r[1], "comments": r[2]} for r in top],
    })


def _t_post_engagement(cur, tenant_id, get_config, args) -> ToolResult:
    sc = args["shortcode"]
    lk = _one(cur, "SELECT COUNT(*) FROM likers WHERE post_shortcode = %(s)s", {"s": sc})[0]
    cm = _one(cur, "SELECT COUNT(*) FROM comments WHERE post_shortcode = %(s)s", {"s": sc})[0]
    return ToolResult("post_engagement", f"POST {sc}: {lk:,} likes, {cm:,} comments",
                      "post", {"type": "post", "shortcode": sc, "likes": lk, "comments": cm})


def _t_bookings_summary(cur, tenant_id, get_config, args) -> ToolResult:
    total_b = _one(cur, "SELECT COUNT(*) FROM bookings WHERE tenant_id = %(t)s",
                   {"t": tenant_id})[0]
    open_b = _one(cur,
        "SELECT COUNT(*) FROM opportunities "
        "WHERE stage = 'booked' AND closed_at IS NULL AND tenant_id = %(t)s",
        {"t": tenant_id})[0]
    upcoming = _rows(cur,
        "SELECT COALESCE(invitee_name,'(unnamed)'), starts_at, status FROM bookings "
        "WHERE tenant_id = %(t)s AND starts_at > NOW() "
        "ORDER BY starts_at ASC LIMIT 3", {"t": tenant_id})
    lines = [f"  {r[0]} — {r[1]:%Y-%m-%d %H:%M} ({r[2]})" for r in upcoming]
    block = (f"BOOKINGS: {total_b} total all-time  |  {open_b} currently in 'Booked' stage" +
             (("\nUPCOMING:\n" + "\n".join(lines)) if lines else ""))
    return ToolResult("bookings_summary", block)      # intent stays general (no widget)


# ── Tools — Person-360 (Option B, ratified 2026-07-05: the operator sees the
#    unvarnished view, including sensitive session summaries — the `sensitive`
#    flag gates OUTWARD channels, not the private cockpit). Rendered as plain
#    intent-"general" text; no widget contract touched. ─────────────────────────

_PERSON_MATCH_SQL = (
    "SELECT DISTINCT p.id, p.display_name, p.wa_ref_code, p.lifecycle_stage, "
    "       p.primary_language, p.last_seen_at "
    "FROM person p "
    "LEFT JOIN person_identity pi ON pi.person_id = p.id "
    "WHERE p.tenant_id = %(t)s "
    "  AND (lower(COALESCE(p.display_name,'')) LIKE %(f)s "
    "       OR lower(COALESCE(p.wa_ref_code,'')) LIKE %(f)s "
    "       OR lower(COALESCE(pi.username,'')) LIKE %(f)s) "
    "ORDER BY p.last_seen_at DESC NULLS LAST "
    "LIMIT 1"
)


def _find_person(cur, tenant_id: str, name: str):
    return _one(cur, _PERSON_MATCH_SQL, {"t": tenant_id, "f": _like(name)})


def _t_person_360(cur, tenant_id, get_config, args) -> ToolResult:
    p = _find_person(cur, tenant_id, args["name"])
    if not p:
        return ToolResult("person_360",
                          f"PERSON: no record matching '{args['name']}' in the spine.")
    pid = p[0]
    name = p[1] or (f"Lead {p[2]}" if p[2] else "Lead")
    lines = [f"PERSON-360 — {name}:",
             f"  Lifecycle: {p[3] or '—'}  |  Language: {p[4] or '—'}  "
             f"|  Last seen: {p[5]:%Y-%m-%d %H:%M}" if p[5] else
             f"  Lifecycle: {p[3] or '—'}  |  Language: {p[4] or '—'}"]

    opp = _one(cur,
        "SELECT stage, stage_entered_at FROM opportunities "
        "WHERE person_id = %(p)s AND tenant_id = %(t)s AND closed_at IS NULL "
        "ORDER BY opened_at DESC LIMIT 1", {"p": pid, "t": tenant_id})
    if opp:
        lines.append(f"  Open opportunity: stage '{opp[0]}' since "
                     f"{opp[1]:%Y-%m-%d %H:%M}" if opp[1] else
                     f"  Open opportunity: stage '{opp[0]}'")

    prof = _one(cur,
        "SELECT summary, facts, updated_at FROM person_profile "
        "WHERE person_id = %(p)s AND tenant_id = %(t)s LIMIT 1",
        {"p": pid, "t": tenant_id})
    if prof:
        if prof[0]:
            lines.append(f"  PROFILE: {str(prof[0])[:600]}")
        if prof[1]:
            facts = prof[1] if isinstance(prof[1], (dict, list)) else str(prof[1])
            lines.append(f"  FACTS: {json.dumps(facts, ensure_ascii=False, default=str)[:400]}")

    sums = _rows(cur,
        "SELECT summary, topic, emotional_state, urgency, sensitive, created_at "
        "FROM session_summaries "
        "WHERE person_id = %(p)s AND tenant_id = %(t)s "
        "ORDER BY created_at DESC LIMIT 3", {"p": pid, "t": tenant_id})
    if sums:
        lines.append("  RECENT SESSION SUMMARIES:")
        for s in sums:
            tag = " [sensitive]" if s[4] else ""
            when = f"{s[5]:%Y-%m-%d}" if s[5] else "?"
            lines.append(f"    · {when}{tag} topic={s[1] or '—'} "
                         f"emotional_state={s[2] or '—'} urgency={s[3] if s[3] is not None else '—'}: "
                         f"{str(s[0] or '')[:350]}")

    acts = _rows(cur,
        "SELECT kind, channel, occurred_at FROM interactions "
        "WHERE person_id = %(p)s AND tenant_id = %(t)s "
        "ORDER BY occurred_at DESC LIMIT 10", {"p": pid, "t": tenant_id})
    if acts:
        lines.append("  RECENT ACTIVITY: " + ";  ".join(
            f"{a[2]:%m-%d %H:%M} {a[0]} ({a[1]})" if a[2] else f"{a[0]} ({a[1]})"
            for a in acts))

    ph = _one(cur,
        "SELECT external_id FROM person_identity "
        "WHERE person_id = %(p)s AND channel = 'whatsapp' LIMIT 1", {"p": pid})
    if ph:
        lines.append(f"  WhatsApp: {ph[0]}")

    return ToolResult("person_360", "\n".join(lines))


def _t_recent_outbound(cur, tenant_id, get_config, args) -> ToolResult:
    params: dict = {"t": tenant_id, "n": args["limit"]}
    name_sql = ""
    if args.get("name"):
        name_sql = ("AND (lower(COALESCE(p.display_name,'')) LIKE %(f)s "
                    "     OR lower(COALESCE(p.wa_ref_code,'')) LIKE %(f)s) ")
        params["f"] = _like(args["name"])
    rows = _rows(cur,
        f"SELECT {_lead_name_sql()}, o.channel, o.body, o.sent_by, o.sent_at "
        f"FROM outbound_messages o JOIN person p ON p.id = o.person_id "
        f"WHERE o.tenant_id = %(t)s {name_sql}"
        f"ORDER BY o.sent_at DESC LIMIT %(n)s", params)
    if not rows:
        who = f" to '{args['name']}'" if args.get("name") else ""
        return ToolResult("recent_outbound", f"OUTBOUND MESSAGES: none logged{who}.")
    lines = [
        f"  {r[4]:%Y-%m-%d %H:%M} → {r[0]} [{r[1]}, by {r[3] or '?'}]: {str(r[2] or '')[:200]}"
        if r[4] else f"  → {r[0]} [{r[1]}]: {str(r[2] or '')[:200]}"
        for r in rows
    ]
    return ToolResult("recent_outbound", "OUTBOUND MESSAGES (latest first):\n" + "\n".join(lines))


def _t_recent_conversations(cur, tenant_id, get_config, args) -> ToolResult:
    # sessions/messages carry no tenant_id — scoped through the person spine.
    params: dict = {"t": tenant_id, "n": args["limit"]}
    name_sql = ""
    if args.get("name"):
        name_sql = ("AND (lower(COALESCE(p.display_name,'')) LIKE %(f)s "
                    "     OR lower(COALESCE(p.wa_ref_code,'')) LIKE %(f)s) ")
        params["f"] = _like(args["name"])
    rows = _rows(cur,
        f"SELECT {_lead_name_sql()}, m.role, m.content, m.created_at "
        f"FROM messages m "
        f"JOIN sessions s ON s.id = m.session_id "
        f"JOIN person p ON p.id = s.person_id "
        f"WHERE p.tenant_id = %(t)s {name_sql}"
        f"ORDER BY m.created_at DESC LIMIT %(n)s", params)
    if not rows:
        who = f" for '{args['name']}'" if args.get("name") else ""
        return ToolResult("recent_conversations", f"CONVERSATIONS: no messages found{who}.")
    lines = [
        f"  {r[3]:%Y-%m-%d %H:%M} {r[0]} · {r[1]}: {str(r[2] or '')[:300]}"
        if r[3] else f"  {r[0]} · {r[1]}: {str(r[2] or '')[:300]}"
        for r in reversed(rows)                        # chronological for readability
    ]
    return ToolResult("recent_conversations",
                      "CONVERSATION MESSAGES (chronological):\n" + "\n".join(lines))


# ── The registry — adding a capability is ONE entry here, never router surgery ─

_STAGE_ARG = {"stage": ArgSpec("enum", required=True, choices=PIPELINE_STAGES)}
_NAME_ARG = {"name": ArgSpec("str", required=True)}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("funnel_overview",
             "Full pipeline funnel: per-stage lead counts, stage→stage conversion %, velocity. "
             "Use for pipeline/funnel overview, drop-off, conversion questions.",
             _t_funnel_overview),
        Tool("stage_pipeline",
             "Open-lead count + avg hours in ONE pipeline stage.",
             _t_stage_pipeline, _STAGE_ARG),
        Tool("stage_velocity",
             "Avg/median hours before advancing + conversion. Args: stage (optional — omit for all stages).",
             _t_stage_velocity,
             {"stage": ArgSpec("enum", choices=PIPELINE_STAGES)}),
        Tool("sla_overview",
             "SLA dashboard: breach/warn/ok counts + top 5 most urgent leads.",
             _t_sla_overview),
        Tool("sla_lead_lookup",
             "One lead's SLA state by person name (or ref code) fragment.",
             _t_sla_lead_lookup, _NAME_ARG),
        Tool("community_metrics",
             "Instagram community totals: size, likes, comments, posts.",
             _t_community_metrics),
        Tool("follower_growth",
             "Weekly new-follower trend (last 8 weeks) + community size.",
             _t_follower_growth),
        Tool("top_posts",
             "Top Instagram posts ranked by likes. Args: limit (1-10, default 5).",
             _t_top_posts,
             {"limit": ArgSpec("int", min_val=1, max_val=10, default=5)}),
        Tool("post_engagement",
             "Likes + comments for ONE Instagram post by shortcode.",
             _t_post_engagement,
             {"shortcode": ArgSpec("shortcode", required=True)}),
        Tool("bookings_summary",
             "Consultation bookings: all-time total, leads in Booked stage, next upcoming.",
             _t_bookings_summary),
        Tool("person_360",
             "Everything known about one person: profile summary, facts, session summaries "
             "(incl. emotional state), recent activity, WhatsApp number. Args: name fragment.",
             _t_person_360, _NAME_ARG),
        Tool("recent_outbound",
             "Messages Erez sent (outreach log), latest first. Args: name (optional), limit (1-10).",
             _t_recent_outbound,
             {"name": ArgSpec("str"), "limit": ArgSpec("int", min_val=1, max_val=10, default=5)}),
        Tool("recent_conversations",
             "Raw inbound/outbound chat messages across channels. Args: name (optional), limit (1-15).",
             _t_recent_conversations,
             {"name": ArgSpec("str"), "limit": ArgSpec("int", min_val=1, max_val=15, default=10)}),
    )
}


def run_tool(step: PlanStep, cur, tenant_id: str, get_config: Callable[[str], str]) -> ToolResult:
    """Execute one validated plan step. The caller owns the (read-only) transaction."""
    tool = TOOLS[step.tool]
    return tool.run(cur, tenant_id, get_config, step.args)


# ── Planner prompt + plan parsing ─────────────────────────────────────────────

def _catalog_lines() -> str:
    out = []
    for t in TOOLS.values():
        if t.args:
            args_doc = ", ".join(
                f"{n} ({'required ' if s.required else ''}{s.kind}"
                + (f": {'|'.join(s.choices)}" if s.choices else "") + ")"
                for n, s in t.args.items())
            out.append(f"- {t.name}: {t.description}  ARGS: {args_doc}")
        else:
            out.append(f"- {t.name}: {t.description}  ARGS: none")
    return "\n".join(out)


def build_planner_prompt(message: str, chips: list[str], history: list[dict]) -> str:
    """
    The planning call. Works on any instruction-following model (Gemini Flash,
    Claude, …): plain prompt in, strict JSON out — no native function-calling API.
    """
    hist = ""
    for m in history[-HISTORY_TURNS:]:
        role = "Operator" if m.get("role") == "user" else "Nexus"
        hist += f"\n{role}: {str(m.get('content', ''))[:300]}"

    chips_line = "\n".join(f"- {c}" for c in chips) if chips else "(none)"

    return (
        "You are the query PLANNER inside Nexus, a private lead-management cockpit "
        "for a solo therapy practice. Your ONLY job is to pick which read-only data "
        "tools to run so the answering step has real data. You never answer the "
        "question yourself and you NEVER write SQL.\n\n"
        f"AVAILABLE TOOLS:\n{_catalog_lines()}\n\n"
        "OUTPUT FORMAT — respond with ONLY this JSON, no prose, no markdown fences:\n"
        '{"plan": [{"tool": "<tool name>", "args": {}}]}\n\n'
        "RULES:\n"
        f"1. At most {MAX_TOOLS_PER_PLAN} steps; usually ONE tool is right.\n"
        "2. The operator may write in Hebrew or English, formally or casually — "
        "match the MEANING of the request to a tool, not exact keywords.\n"
        "3. If the message mentions a specific person, prefer person-specific tools "
        "and pass their name fragment in the 'name' arg exactly as written.\n"
        "4. CONTEXT CHIPS below were attached by the UI from what the operator is "
        "looking at — treat each chip as a strong hint for one tool.\n"
        "5. Only tool names from the list above; only their documented args.\n"
        '6. If the message needs no data (greeting, thanks, general how-to), return {"plan": []}.\n\n'
        f"CONTEXT CHIPS:\n{chips_line}\n"
        f"{('RECENT CONVERSATION:' + hist) if hist else ''}\n"
        f"OPERATOR MESSAGE: {message or '(no text — chips only; plan from the chips)'}\n\n"
        "JSON:"
    )


def parse_plan(parsed: Any) -> list[PlanStep]:
    """
    Turn the (already JSON-parsed) planner output into validated PlanSteps.

    Raises PlanError when the output is structurally unusable — the endpoint
    treats that as "fall back to the legacy router". An empty plan is VALID
    (the model decided no data is needed); invalid individual steps are
    dropped, but if every step was invalid we raise (the model tried to fetch
    something and failed — legacy routing is safer than answering dataless).
    """
    if not isinstance(parsed, dict) or not isinstance(parsed.get("plan"), list):
        raise PlanError("planner output missing 'plan' list")
    raw_steps = parsed["plan"][:MAX_TOOLS_PER_PLAN]
    steps: list[PlanStep] = []
    for raw in raw_steps:
        try:
            if not isinstance(raw, dict):
                raise PlanError("step is not an object")
            name = str(raw.get("tool", "")).strip()
            tool = TOOLS.get(name)
            if tool is None:
                raise PlanError(f"unknown tool {name!r}")
            steps.append(PlanStep(name, validate_args(tool, raw.get("args"))))
        except PlanError:
            continue
    if raw_steps and not steps:
        raise PlanError("all plan steps were invalid")
    # De-duplicate identical steps (models occasionally repeat themselves).
    seen: set = set()
    unique: list[PlanStep] = []
    for s in steps:
        key = (s.tool, tuple(sorted(s.args.items())))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


# ── Grounded reply prompt + contract assembly ─────────────────────────────────

PIPELINE_REF = (
    "Pipeline stages (in order): "
    "Engaged (24h SLA) → Qualified (48h) → Captured (72h) → "
    "Briefed (48h) → Booked (168h).  "
    "'Booked' is the north-star conversion metric."
)


def build_reply_prompt(message: str, chips: list[str], history: list[dict],
                       context_blocks: list[str]) -> str:
    """The answering call: same voice as the legacy router, hard-grounded."""
    system = (
        "You are Nexus AI — the analytics brain inside Erez Gartsman's private "
        "command center (the Nexus Cockpit) for his coaching and therapy practice.\n"
        "Speak like a sharp analyst briefing the operator: concise, data-driven, "
        "actionable. Use the real numbers provided. Flag what needs attention. "
        "Suggest one clear next action when relevant. Respond in English.\n"
        "GROUNDING RULES (absolute): answer ONLY from the LIVE DATA section below. "
        "If there is no LIVE DATA section, or it does not contain what the question "
        "needs, say so plainly and suggest what to ask instead — NEVER invent or "
        "estimate a number, name, date, or phone number.\n\n"
        f"PIPELINE: {PIPELINE_REF}"
    )
    if context_blocks:
        system += "\n\nLIVE DATA pulled for this query:\n" + "\n\n".join(context_blocks)
    if chips:
        system += "\n\nCONTEXT CHIPS the operator attached: " + "; ".join(chips)

    hist_lines = ""
    for m in history[-HISTORY_TURNS:]:
        role = "User" if m.get("role") == "user" else "Nexus"
        hist_lines += f"\n{role}: {str(m.get('content', ''))[:400]}"
    if hist_lines:
        system += f"\n\nCONVERSATION SO FAR:{hist_lines}"

    user_turn = message or ("(No text — the user attached the context chips above. "
                            "Analyse and provide insight.)")
    return f"{system}\n\nUser: {user_turn}\n\nNexus:"


def resolve_contract(results: list[ToolResult]) -> tuple[str, dict | None]:
    """
    (intent, context_data) from executed results — deterministic, first tool
    that claims an intent wins (mirrors the legacy "first chip wins" rule).
    """
    for r in results:
        if r.intent and r.intent in FROZEN_INTENTS:
            return r.intent, r.ctx_data
    return "general", None
