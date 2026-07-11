"""
nexus.flows.authoring — flow definition editing + the simulation-gated publish
(SYSTEM_ELEVATION_PRD.md §F3).

The version discipline the 009 header promised, enforced here:
  • Published/paused rows are IMMUTABLE. Editing one forks a NEW draft row at
    version+1, same slug. Drafts are freely mutable.
  • Publishing a draft runs the 90-day simulation server-side as the
    AUTHORITATIVE gate (the UI's dialog is advisory; this is the real barrier),
    stores the report on the row, flips the draft → published, and archives any
    prior published version of the same slug so the one-published-per-slug
    partial unique index (migration 009) always holds.
  • Kill switches: pause (published→paused), resume (paused→published), archive.

Graph validation is strict — a published flow that the runner can't walk is a
silent failure waiting to happen, so publish refuses an invalid graph up front.

Commit-free helpers (caller owns the transaction) except where noted; raises
AuthoringError with a clean message the router turns into a 4xx.
"""
from __future__ import annotations

import json
import logging
import re

from nexus.flows import predicates as flow_predicates

logger = logging.getLogger("nexus.flows.authoring")

_VALID_NODE_TYPES = {
    "trigger", "condition", "wait",
    "action:send_message", "action:notify_operator", "action:advance_stage",
    "action:add_note", "action:set_flag",
}
_EDITABLE_STATUSES = {"draft"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class AuthoringError(ValueError):
    """A validation / state-machine violation the router surfaces as a 4xx."""


# ── Validation ────────────────────────────────────────────────────────────────

def validate_graph(graph: dict) -> None:
    """Raise AuthoringError unless the graph is one the runner can execute:
    exactly one trigger, known node types, unique ids, edges between real
    nodes, every non-trigger node reachable from the trigger."""
    if not isinstance(graph, dict):
        raise AuthoringError("graph must be an object")
    nodes = graph.get("nodes")
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        raise AuthoringError("a flow needs at least one node")
    if not isinstance(edges, list):
        raise AuthoringError("edges must be a list")

    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)) or any(not i for i in ids):
        raise AuthoringError("every node needs a unique, non-empty id")

    triggers = [n for n in nodes if n.get("type") == "trigger"]
    if len(triggers) != 1:
        raise AuthoringError("a flow must have exactly one trigger node")

    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        if n.get("type") not in _VALID_NODE_TYPES:
            raise AuthoringError(f"unknown node type {n.get('type')!r}")
        if n.get("type") == "condition":
            try:
                flow_predicates.validate(n.get("predicate") or {})
            except flow_predicates.PredicateError as e:
                raise AuthoringError(f"condition node {n['id']}: {e}") from e
        if n.get("type") == "wait":
            hours = n.get("hours")
            if not isinstance(hours, (int, float)) or hours <= 0:
                raise AuthoringError(f"wait node {n['id']} needs a positive 'hours'")

    for e in edges:
        if e.get("from") not in by_id or e.get("to") not in by_id:
            raise AuthoringError("an edge references a node that doesn't exist")

    # Reachability from the trigger.
    adj: dict[str, list[str]] = {i: [] for i in by_id}
    for e in edges:
        adj[e["from"]].append(e["to"])
    seen = set()
    stack = [triggers[0]["id"]]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, []))
    unreachable = [i for i in by_id if i not in seen]
    if unreachable:
        raise AuthoringError(f"nodes not reachable from the trigger: {', '.join(unreachable)}")


def validate_trigger(trigger: dict) -> None:
    if not isinstance(trigger, dict):
        raise AuthoringError("trigger must be an object")
    ttype = trigger.get("type")
    if ttype == "event":
        if not trigger.get("kind"):
            raise AuthoringError("an event trigger needs a 'kind'")
    elif ttype == "state":
        try:
            flow_predicates.validate(trigger.get("predicate") or {})
        except flow_predicates.PredicateError as e:
            raise AuthoringError(f"state trigger predicate: {e}") from e
    else:
        raise AuthoringError("trigger type must be 'event' or 'state'")


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return s or "flow"


# ── Reads ─────────────────────────────────────────────────────────────────────

def load_flow(conn, flow_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug, version, status, live, name, description, graph, trigger "
            "FROM flow_definitions WHERE id = %s",
            (flow_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]), "slug": row[1], "version": row[2], "status": row[3],
        "live": row[4], "name": row[5], "description": row[6], "graph": row[7], "trigger": row[8],
    }


# ── Mutations (commit-free — router owns the transaction) ─────────────────────

def create_draft(conn, *, name: str, description: str | None,
                 trigger: dict, graph: dict, created_by: str) -> str:
    """Create a new draft flow (a fresh slug, version 1). Validates first."""
    if not name or not name.strip():
        raise AuthoringError("a flow needs a name")
    validate_trigger(trigger)
    validate_graph(graph)
    slug = _unique_slug(conn, slugify(name))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO flow_definitions "
            "(slug, version, status, name, description, graph, trigger, created_by) "
            "VALUES (%s, 1, 'draft', %s, %s, %s::jsonb, %s::jsonb, %s) RETURNING id",
            (slug, name.strip(), description, json.dumps(graph), json.dumps(trigger), created_by),
        )
        return str(cur.fetchone()[0])


def update_draft(conn, flow_id: str, *, name=None, description=None,
                 trigger=None, graph=None) -> None:
    """Patch a DRAFT flow. Published/paused/archived rows are immutable —
    editing one is a separate fork_draft() call, never an in-place update."""
    flow = load_flow(conn, flow_id)
    if flow is None:
        raise AuthoringError("flow not found")
    if flow["status"] not in _EDITABLE_STATUSES:
        raise AuthoringError(f"a {flow['status']} flow is immutable — fork a new draft to edit it")

    if trigger is not None:
        validate_trigger(trigger)
    if graph is not None:
        validate_graph(graph)

    sets, params = [], []
    if name is not None:
        if not name.strip():
            raise AuthoringError("name cannot be empty")
        sets.append("name = %s"); params.append(name.strip())
    if description is not None:
        sets.append("description = %s"); params.append(description)
    if trigger is not None:
        sets.append("trigger = %s::jsonb"); params.append(json.dumps(trigger))
    if graph is not None:
        sets.append("graph = %s::jsonb"); params.append(json.dumps(graph))
    if not sets:
        return
    sets.append("updated_at = NOW()")
    params.append(flow_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE flow_definitions SET {', '.join(sets)} WHERE id = %s", params)


def fork_draft(conn, flow_id: str, *, created_by: str) -> str:
    """Fork a published/paused flow into a new editable draft at version+1,
    same slug. The published row stays live and untouched."""
    flow = load_flow(conn, flow_id)
    if flow is None:
        raise AuthoringError("flow not found")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(version), 0) FROM flow_definitions WHERE slug = %s",
            (flow["slug"],),
        )
        next_version = cur.fetchone()[0] + 1
        cur.execute(
            "INSERT INTO flow_definitions "
            "(slug, version, status, name, description, graph, trigger, created_by) "
            "VALUES (%s, %s, 'draft', %s, %s, %s::jsonb, %s::jsonb, %s) RETURNING id",
            (flow["slug"], next_version, flow["name"], flow["description"],
             json.dumps(flow["graph"]), json.dumps(flow["trigger"]), created_by),
        )
        return str(cur.fetchone()[0])


def publish(conn, flow_id: str, *, simulation: dict) -> None:
    """Publish a validated draft, gated on a completed simulation. Archives
    any prior published version of the same slug so one-published-per-slug
    holds. `simulation` is the authoritative report the router just ran."""
    flow = load_flow(conn, flow_id)
    if flow is None:
        raise AuthoringError("flow not found")
    if flow["status"] != "draft":
        raise AuthoringError(f"only a draft can be published (this is {flow['status']})")
    validate_trigger(flow["trigger"])
    validate_graph(flow["graph"])
    if not isinstance(simulation, dict) or "fires" not in simulation:
        raise AuthoringError("publish requires a completed simulation")

    with conn.cursor() as cur:
        # Archive the currently-published sibling (if any) so the partial
        # unique index (one published per slug) never trips.
        cur.execute(
            "UPDATE flow_definitions SET status = 'archived', updated_at = NOW() "
            "WHERE slug = %s AND status = 'published' AND id <> %s",
            (flow["slug"], flow_id),
        )
        cur.execute(
            "UPDATE flow_definitions "
            "SET status = 'published', published_at = NOW(), updated_at = NOW(), "
            "    last_simulation = %s::jsonb "
            "WHERE id = %s",
            (json.dumps(simulation), flow_id),
        )


def set_status(conn, flow_id: str, *, action: str) -> str:
    """Kill switches: pause | resume | archive. Returns the new status."""
    flow = load_flow(conn, flow_id)
    if flow is None:
        raise AuthoringError("flow not found")
    transitions = {
        ("published", "pause"): "paused",
        ("paused", "resume"): "published",
        ("published", "archive"): "archived",
        ("paused", "archive"): "archived",
        ("draft", "archive"): "archived",
    }
    new_status = transitions.get((flow["status"], action))
    if new_status is None:
        raise AuthoringError(f"cannot {action} a {flow['status']} flow")
    if new_status == "published":
        # Resuming must respect one-published-per-slug.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM flow_definitions WHERE slug = %s AND status = 'published' AND id <> %s LIMIT 1",
                (flow["slug"], flow_id),
            )
            if cur.fetchone():
                raise AuthoringError("another version of this flow is already published")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_definitions SET status = %s, updated_at = NOW() WHERE id = %s",
            (new_status, flow_id),
        )
    return new_status


def set_live(conn, flow_id: str, *, live: bool) -> None:
    """Flip a flow out of shadow mode (live=true) or back. Only a published
    flow can go live — a draft has nothing running to make real."""
    flow = load_flow(conn, flow_id)
    if flow is None:
        raise AuthoringError("flow not found")
    if live and flow["status"] != "published":
        raise AuthoringError("only a published flow can go live")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_definitions SET live = %s, updated_at = NOW() WHERE id = %s",
            (live, flow_id),
        )


def _unique_slug(conn, base: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT slug FROM flow_definitions WHERE slug LIKE %s", (base + "%",))
        taken = {r[0] for r in cur.fetchall()}
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"
