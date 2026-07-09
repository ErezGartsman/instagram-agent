"""
routers.cockpit — every /api/cockpit/* endpoint (E0 strangler extraction).

Route bodies moved VERBATIM from main.py except that module-level helpers are
referenced late-bound as main.<name>. That is deliberate, twice over:
  1. tests patch("main.<helper>") — late binding keeps every mock working;
  2. helpers migrate into nexus/ later without touching these routes again.
main.py mounts this router at the very bottom of the module, so every main.*
attribute is defined by the time FastAPI evaluates the decorators here.
"""
from fastapi import APIRouter

import main

router = APIRouter()

@router.get("/api/cockpit/me")
def cockpit_me(user: dict = main.Depends(main.require_cockpit_user)):
    """
    Identity probe for the Cockpit SPA. The frontend calls this after a Supabase
    magic-link sign-in to confirm the session is valid server-side (and that the
    account is approved) before it trusts the client-side session.
    """
    return {
        "id":    user.get("sub"),
        "email": user.get("email"),
        "role":  user.get("role"),
    }


@router.get("/api/cockpit/pipeline")
def cockpit_pipeline(user: dict = main.Depends(main.require_cockpit_user)):
    """
    Open opportunities grouped into the forward-only pipeline stages, for the
    Cockpit lead board. One open opportunity per person (closed_at IS NULL),
    enriched with the profile summary (intent) and the last-activity timestamp.
    """
    stages = main.nexus_interactions.PIPELINE_STAGES
    buckets: dict[str, list] = {s: [] for s in stages}
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT o.id, o.stage, o.source_channel, o.stage_entered_at, "
                    "       p.id, p.display_name, p.wa_ref_code, "
                    "       pp.summary, li.last_at "
                    "FROM opportunities o "
                    "JOIN person p ON p.id = o.person_id "
                    "LEFT JOIN person_profile pp ON pp.person_id = p.id "
                    "LEFT JOIN (SELECT person_id, MAX(occurred_at) AS last_at "
                    "           FROM interactions GROUP BY person_id) li "
                    "       ON li.person_id = p.id "
                    "WHERE o.closed_at IS NULL "
                    "ORDER BY COALESCE(li.last_at, o.stage_entered_at) DESC NULLS LAST"
                )
                rows = cur.fetchall()
        for r in rows:
            (opp_id, stage, channel, stage_entered_at, person_id,
             display_name, wa_ref, summary, last_at) = r
            if stage not in buckets:
                continue  # terminal / unknown stage — not shown on the board
            buckets[stage].append({
                "id":               str(opp_id),
                "person_id":        str(person_id),
                "name":             display_name or (f"Lead {wa_ref}" if wa_ref else "Lead"),
                "wa_ref":           wa_ref,
                "channel":          channel,
                "intent":           summary,
                "last_contacted":   last_at.isoformat() if last_at else None,
                "stage_entered_at": stage_entered_at.isoformat() if stage_entered_at else None,
            })
        return {
            "status": "success",
            "stages": [
                {"stage": s, "count": len(buckets[s]), "leads": buckets[s]}
                for s in stages
            ],
        }
    except Exception as e:
        main.logger.error(f"[cockpit/pipeline] query failed: {e}")
        return {"status": "error", "detail": "Could not load the pipeline."}


@router.get("/api/cockpit/queue")
def cockpit_queue(user: dict = main.Depends(main.require_cockpit_user)):
    """
    The Work Queue — the Decision Engine's surface. One ranked row per OPEN
    opportunity, each carrying the recommended next move (Action), the engine's
    Confidence, and the Reason, plus a memory-first Person-360 (essence / goal /
    tension) and a V1 activity timeline derived from the signal log + the latest
    session summary. Ranking + recommendation live in nexus.work_queue (pure,
    unit-tested); this endpoint only gathers rows and assembles the response.
    """
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT o.id, o.stage, o.source_channel, "
                    "       p.id, p.display_name, p.wa_ref_code, p.first_seen_at, "
                    "       pp.summary, pp.attributes, "
                    "       agg.last_at, "
                    "       ss.urgency, ss.emotional_state, ss.topic, ss.created_at "
                    "FROM opportunities o "
                    "JOIN person p ON p.id = o.person_id "
                    "LEFT JOIN person_profile pp ON pp.person_id = p.id "
                    "LEFT JOIN LATERAL (SELECT MAX(occurred_at) AS last_at "
                    "                   FROM interactions WHERE person_id = p.id) agg ON TRUE "
                    "LEFT JOIN LATERAL (SELECT urgency, emotional_state, topic, created_at "
                    "                   FROM session_summaries WHERE person_id = p.id "
                    "                   ORDER BY created_at DESC LIMIT 1) ss ON TRUE "
                    "WHERE o.closed_at IS NULL "
                    "  AND (o.snoozed_until IS NULL OR o.snoozed_until <= NOW())"
                )
                rows = cur.fetchall()
                person_ids = [r[3] for r in rows]
                recent: dict[str, list] = {}
                if person_ids:
                    cur.execute(
                        "SELECT person_id, kind, occurred_at FROM interactions "
                        "WHERE person_id = ANY(%s::uuid[]) ORDER BY occurred_at DESC",
                        (person_ids,),
                    )
                    for pid, kind, occurred_at in cur.fetchall():
                        recent.setdefault(str(pid), []).append((kind, occurred_at))

        now = main.datetime.datetime.now(main.datetime.timezone.utc)
        items = []
        for r in rows:
            (opp_id, stage, channel, person_id, display_name, wa_ref, first_seen_at,
             summary, attributes, last_at, urgency, emotional_state, topic, ss_at) = r
            pid = str(person_id)
            events = recent.get(pid, [])
            hours = (now - last_at).total_seconds() / 3600 if last_at else None
            rec = main.nexus_work_queue.recommend(main.nexus_work_queue.Signals(
                stage=stage,
                hours_since_last=hours,
                recent_kinds=frozenset(k for (k, _t) in events),
                urgency=urgency,
            ))
            timeline = [
                {"kind": k, "label": main.nexus_work_queue.label_for_kind(k),
                 "at": t.isoformat() if t else None}
                for (k, t) in events[:6]
            ]
            if topic or emotional_state:
                timeline.append({
                    "kind": "session_summary",
                    "label": "Session · " + (topic or emotional_state or "summary"),
                    "at": ss_at.isoformat() if ss_at else None,
                })
                timeline.sort(key=lambda e: e["at"] or "", reverse=True)

            attrs = attributes if isinstance(attributes, dict) else {}
            name = display_name or (f"Lead {wa_ref}" if wa_ref else "Lead")
            items.append({
                "id":             str(opp_id),
                "person_id":      pid,
                "name":           name,
                "initials":       main.nexus_work_queue.initials(name),
                "channel":        channel,
                "handle":         wa_ref,
                "teaser":         rec.reason,
                "action":         rec.action,
                "confidence":     rec.confidence,
                "reason":         rec.reason,
                "last_contacted": last_at.isoformat() if last_at else None,
                "first_seen_at":  first_seen_at.isoformat() if first_seen_at else None,
                "timeline":       timeline,
                "essence":        summary,
                "goal":           attrs.get("goal"),
                "tension":        attrs.get("tension") or emotional_state,
                "_priority":      rec.priority,
            })

        items.sort(key=lambda it: (it["_priority"], it["last_contacted"] or ""), reverse=True)
        for it in items:
            it.pop("_priority", None)
        return {"status": "success", "items": items}
    except Exception as e:
        main.logger.error(f"[cockpit/queue] query failed: {e}")
        return {"status": "error", "detail": "Could not load the work queue."}


@router.get("/api/cockpit/thread/{person_id}")
def cockpit_thread(person_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """
    One Thread — a person's conversation across ALL channels. Merges inbound
    messages with operator-authored outbound messages, oldest-first, each
    tagged with its channel (see _db_person_thread).

    `channels` carries per-channel send-eligibility for every channel One
    Thread can send on (WhatsApp/Instagram: 24h free-form window; Telegram: no
    window) and `default_channel` (reply-to-last-inbound) so the composer can
    pre-select a channel and grey out Send with a real reason instead of
    failing opaquely.
    """
    try:
        with main.get_db_conn() as conn:
            messages = main._db_person_thread(conn, person_id)
            channels = {
                ch: main._channel_send_eligibility(conn, person_id, ch)
                for ch in main._SUPPORTED_SEND_CHANNELS
            }
        return {
            "status": "success",
            "messages": messages,
            "channels": channels,
            "default_channel": main._resolve_default_channel(messages),
        }
    except Exception as e:
        main.logger.error(f"[cockpit/thread] query failed for {person_id}: {e}")
        return {"status": "error", "detail": "Could not load conversation."}


@router.get("/api/cockpit/briefing")
def cockpit_briefing(user: dict = main.Depends(main.require_cockpit_user)):
    """
    The Morning Briefing — "what changed overnight", as a deterministic diff of
    the last 24h: people who reopened after ≥7 days of silence, new leads that
    arrived, and SLA warn/breach accountability. Items shape = the frontend
    MorningBriefing contract ({tone, headline, detail, href, cta}); an empty
    items list means a quiet night (the card simply doesn't render).
    """
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                # 1. Reopened after silence: first person-activity event in the
                #    window, measured against their last activity BEFORE it.
                cur.execute(
                    "WITH recent AS ("
                    "  SELECT person_id, MIN(occurred_at) AS returned_at"
                    "  FROM interactions"
                    "  WHERE occurred_at >= NOW() - interval '24 hours'"
                    "    AND person_id IS NOT NULL AND kind = ANY(%(kinds)s)"
                    "  GROUP BY person_id"
                    "), prior AS ("
                    "  SELECT r.person_id, r.returned_at, MAX(i.occurred_at) AS last_before"
                    "  FROM recent r"
                    "  JOIN interactions i ON i.person_id = r.person_id"
                    "   AND i.occurred_at < r.returned_at AND i.kind = ANY(%(kinds)s)"
                    "  GROUP BY r.person_id, r.returned_at"
                    ") "
                    "SELECT p.id, COALESCE(p.display_name, 'Lead '||p.wa_ref_code, 'Lead'), "
                    "       EXTRACT(EPOCH FROM (pr.returned_at - pr.last_before))/86400.0 "
                    "FROM prior pr JOIN person p ON p.id = pr.person_id "
                    "WHERE pr.last_before < pr.returned_at - make_interval(days => %(gap)s) "
                    "ORDER BY 3 DESC LIMIT 5",
                    {"kinds": main._PERSON_ACTIVITY_KINDS,
                     "gap": main.nexus_dossier.REOPEN_GAP_DAYS},
                )
                reopened = [
                    {"person_id": str(r[0]), "name": r[1], "gap_days": float(r[2])}
                    for r in cur.fetchall()
                ]

                # 2. New leads: opportunities opened in the window.
                cur.execute(
                    "SELECT COALESCE(p.display_name, 'Lead '||p.wa_ref_code, 'Lead') "
                    "FROM opportunities o JOIN person p ON p.id = o.person_id "
                    "WHERE o.opened_at >= NOW() - interval '24 hours' "
                    "ORDER BY o.opened_at DESC LIMIT 10"
                )
                new_leads = [r[0] for r in cur.fetchall()]

                # 3. Accountability: current warn/breach roster (migration 004 view).
                cur.execute(
                    "SELECT s.sla_status, "
                    "       COALESCE(s.person_name, 'Lead '||p.wa_ref_code, 'Lead') "
                    "FROM lead_sla_status s JOIN person p ON p.id = s.person_id "
                    "  AND p.tenant_id = %(t)s "
                    "WHERE s.sla_status IN ('warn','breach') "
                    "ORDER BY s.hours_since_touch DESC NULLS LAST LIMIT 20",
                    {"t": main.nexus_ai_planner.DEFAULT_TENANT_ID},
                )
                warn_names, breach_names = [], []
                for status, nm in cur.fetchall():
                    (breach_names if status == "breach" else warn_names).append(nm)

        items = main.nexus_dossier.build_briefing_items(
            reopened=reopened, new_leads=new_leads,
            warn_names=warn_names, breach_names=breach_names)
        return {
            "status": "success",
            "compiled_at": main.datetime.datetime.now(main.datetime.timezone.utc).isoformat(),
            "items": items,
        }
    except Exception as e:
        main.logger.error(f"[cockpit/briefing] query failed: {e}")
        return {"status": "error", "detail": "Could not compile the briefing."}


@router.get("/api/cockpit/person/{person_id}/dossier")
def cockpit_person_dossier(person_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """
    The Person Dossier — the "held, not filed" deep-memory view in ONE payload:
      person   — identity + Person-360 header (essence / goal / tension, stage,
                 held-since, live memory-item count)
      chapters — AI-summarized story chapters (nexus.dossier over the formed
                 session_summaries; silences become "Went quiet" chapters)
      trajectory — urgency-derived relationship line, calm positive
      timeline — the raw signal log (person_timeline), latest 30
    """
    try:
        pid = str(main.uuid.UUID(person_id))
    except ValueError:
        return {"status": "error", "detail": "Person not found."}
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT p.display_name, p.wa_ref_code, p.first_seen_at, "
                    "       pp.summary, pp.attributes, pp.facts, "
                    "       o.stage, o.source_channel, ss.emotional_state "
                    "FROM person p "
                    "LEFT JOIN person_profile pp ON pp.person_id = p.id "
                    "LEFT JOIN LATERAL (SELECT stage, source_channel FROM opportunities "
                    "                   WHERE person_id = p.id AND closed_at IS NULL "
                    "                   ORDER BY opened_at DESC LIMIT 1) o ON TRUE "
                    "LEFT JOIN LATERAL (SELECT emotional_state FROM session_summaries "
                    "                   WHERE person_id = p.id "
                    "                   ORDER BY created_at DESC LIMIT 1) ss ON TRUE "
                    "WHERE p.id = %s",
                    (pid,),
                )
                row = cur.fetchone()
                if row is None:
                    return {"status": "error", "detail": "Person not found."}
                (display_name, wa_ref, first_seen_at, summary, attributes,
                 facts, stage, source_channel, emotional_state) = row

                cur.execute(
                    "SELECT summary, topic, emotional_state, urgency, sensitive, created_at "
                    "FROM session_summaries WHERE person_id = %s "
                    "ORDER BY created_at ASC LIMIT 100",
                    (pid,),
                )
                summaries = [
                    {"summary": r[0], "topic": r[1], "emotional_state": r[2],
                     "urgency": r[3], "sensitive": r[4], "created_at": r[5]}
                    for r in cur.fetchall()
                ]

                cur.execute(
                    "SELECT kind, occurred_at FROM interactions "
                    "WHERE person_id = %s ORDER BY occurred_at DESC LIMIT 30",
                    (pid,),
                )
                timeline = [
                    {"kind": k, "label": main.nexus_work_queue.label_for_kind(k),
                     "at": t.isoformat() if t else None}
                    for (k, t) in cur.fetchall()
                ]

        attrs = attributes if isinstance(attributes, dict) else {}
        facts_list = facts if isinstance(facts, list) else []
        name = display_name or (f"Lead {wa_ref}" if wa_ref else "Lead")
        return {
            "status": "success",
            "person": {
                "id": pid,
                "name": name,
                "initials": main.nexus_work_queue.initials(name),
                "channel": source_channel or "whatsapp",
                "handle": wa_ref,
                "stage": stage,
                "held_since": first_seen_at.isoformat() if first_seen_at else None,
                "essence": summary,
                "goal": attrs.get("goal"),
                "tension": attrs.get("tension") or emotional_state,
                "memory_count": len(facts_list) + len(summaries),
            },
            "chapters": main.nexus_dossier.build_chapters(summaries),
            "trajectory": main.nexus_dossier.build_trajectory(summaries),
            "timeline": timeline,
        }
    except Exception as e:
        main.logger.error(f"[cockpit/dossier] query failed for {person_id}: {e}")
        return {"status": "error", "detail": "Could not load the dossier."}


@router.get("/api/cockpit/copilot/context")
def cockpit_copilot_context(person_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """
    Read-only context envelope: Person-360 + WS1 thread + assembled prompt text.
    Used by the WS4 draft composer to show the Copilot what it's grounded in.
    Never calls the model.
    """
    try:
        with main.get_db_conn() as conn:
            person = main._db_person360(conn, person_id)
            if person is None:
                raise main.HTTPException(status_code=404, detail="Lead not found.")
            thread = main._db_person_thread(conn, person_id)
    except main.HTTPException:
        raise
    except Exception as e:
        main.logger.error(f"[cockpit/copilot/context] failed for {person_id}: {e}")
        return {"status": "error", "detail": "Could not load Copilot context."}

    return {
        "status": "success",
        "person": person,
        "thread": thread,
        "envelope": main.nexus_copilot.build_context_envelope(person, thread),
    }


@router.post("/api/cockpit/copilot/stream")
def cockpit_copilot_stream(body: main.CopilotStreamBody,
                           user: dict = main.Depends(main.require_cockpit_user)):
    """
    Stream a reply draft as Server-Sent Events (text/event-stream).
    Events: `data: {"type":"delta","text":"…"}` per word,
            `data: {"type":"done","text":"<full>"}` on completion,
            `data: {"type":"error","detail":"…"}` on failure.
    Powered by Gemini (gemini-2.5-flash) via the existing _call_llm seam.
    COPILOT_DEMO_MOCK=1 routes to nexus_copilot.demo_draft_for() instead.
    The Copilot never sends — the draft is reviewed by Erez before dispatch.
    """
    try:
        with main.get_db_conn() as conn:
            person = main._db_person360(conn, body.person_id)
            if person is None:
                raise main.HTTPException(status_code=404, detail="Lead not found.")
            thread = main._db_person_thread(conn, body.person_id)
    except main.HTTPException:
        raise
    except Exception as e:
        main.logger.error(f"[cockpit/copilot/stream] context failed for {body.person_id}: {e}")
        raise main.HTTPException(status_code=500, detail="Could not load Copilot context.")

    def _event_source():
        try:
            if main.settings.copilot_demo_mock:
                # Demo-safe path: high-quality pre-baked Hebrew draft, no API call.
                full_text = main.nexus_copilot.demo_draft_for(person)
            else:
                prompt = main.nexus_copilot.build_draft_prompt(person, thread, body.intent)
                full_text = main._call_llm(prompt)
            yield from main._sse_word_stream(full_text)
        except Exception as e:
            main.logger.error(f"[cockpit/copilot/stream] draft failed for {body.person_id}: {e}")
            yield f"data: {main.json.dumps({'type': 'error', 'detail': 'Draft failed — try again.'}, ensure_ascii=False)}\n\n"

    return main.StreamingResponse(
        _event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/cockpit/queue/{opportunity_id}/action")
def cockpit_queue_action(opportunity_id: str, body: main.QueueActionBody,
                         background_tasks: main.BackgroundTasks,
                         user: dict = main.Depends(main.require_cockpit_user)):
    """
    Apply one Work Queue move to an opportunity:

      send    → record the outreach (`contacted`); lead stays OPEN (recency drop).
      done    → "handled today": a short cool-off snooze; stays OPEN.
      snooze  → explicit defer (snooze_hours, default 24h); stays OPEN.
      dismiss → close the opportunity as 'lost'.

    Idempotent where it matters: dismiss on an already-closed lead is a 200 no-op;
    acting (send/done/snooze) on a closed lead is 409. Unknown id → 404; unknown
    action → 400; anything unexpected → 500. Every move logs the operator's
    decision (attributed via `by`) — the feedback the ranking engine will learn from.
    """
    action = (body.type or "").strip().lower()
    if action not in main._QUEUE_ACTIONS:
        raise main.HTTPException(status_code=400, detail=f"Unknown action {body.type!r}.")
    by = user.get("email") or user.get("sub") or "operator"
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT person_id, stage, closed_at "
                    "FROM opportunities WHERE id = %s",
                    (opportunity_id,),
                )
                row = cur.fetchone()
            if row is None:
                raise main.HTTPException(status_code=404, detail="Opportunity not found.")
            person_id, stage, closed_at = str(row[0]), row[1], row[2]

            if closed_at is not None:
                # Already closed: dismiss is a benign no-op; acting on it is a conflict.
                if action == "dismiss":
                    return {"status": "success", "id": opportunity_id, "type": action,
                            "stage": stage, "closed": True, "snoozed_until": None}
                raise main.HTTPException(status_code=409, detail="This lead is already closed.")

            snoozed_until = None
            closed = False
            if action == "send":
                main._dispatch_outreach(conn, person_id, opportunity_id, body.message,
                                   by=by, reason=body.reason)
            elif action == "done":
                snoozed_until = main.nexus_interactions.snooze_opportunity(
                    conn, opportunity_id, hours=main._DONE_COOLOFF_HOURS,
                    kind="handled", by=by, reason=body.reason)
            elif action == "snooze":
                hours = (body.snooze_hours if (body.snooze_hours and body.snooze_hours > 0)
                         else main._SNOOZE_DEFAULT_HOURS)
                snoozed_until = main.nexus_interactions.snooze_opportunity(
                    conn, opportunity_id, hours=hours,
                    kind="snoozed", by=by, reason=body.reason)
            elif action == "dismiss":
                main.nexus_interactions.close_opportunity(
                    conn, opportunity_id, "lost", reason=body.reason, by=by)
                closed, stage = True, "lost"
            conn.commit()

        # Fire the qualification agent in the background for non-dismissed
        # 'engaged' leads — it will auto-advance if goal+tension are now present,
        # or send a WA info request if they're still missing (with 48h dedup).
        if not closed and stage == "engaged":
            background_tasks.add_task(
                main.run_agent,
                agent_type="qualification",
                person_id=person_id,
                triggered_by="action_loop",
                agent_fn=main.qualification_agent,
                input_snapshot={"opportunity_id": opportunity_id, "action": action},
            )

        return {"status": "success", "id": opportunity_id, "type": action,
                "stage": stage, "closed": closed,
                "snoozed_until": snoozed_until.isoformat() if snoozed_until else None}
    except main.HTTPException:
        raise
    except Exception as e:
        main.logger.error(f"[cockpit/queue/action] {action} on {opportunity_id} failed: {e}")
        raise main.HTTPException(status_code=500, detail="Could not apply the action.")


@router.get("/api/cockpit/agents/runs/{person_id}")
def cockpit_agent_runs(person_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """
    Agent run history for a specific person — powers the cockpit AgentActivityFeed
    and AgentPip status indicator. Returns runs newest-first with their actions.
    """
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, agent_type, status, triggered_by, "
                    "       output, error, started_at, completed_at "
                    "FROM agent_runs "
                    "WHERE person_id = %s "
                    "ORDER BY started_at DESC "
                    "LIMIT 20",
                    (person_id,),
                )
                run_rows = cur.fetchall()
                run_ids = [str(r[0]) for r in run_rows]
                actions_by_run: dict[str, list] = {rid: [] for rid in run_ids}
                if run_ids:
                    cur.execute(
                        "SELECT agent_run_id, action_type, payload, result, at "
                        "FROM agent_actions "
                        "WHERE agent_run_id = ANY(%s) "
                        "ORDER BY at ASC",
                        (run_ids,),
                    )
                    for run_id, action_type, payload, result, at in cur.fetchall():
                        actions_by_run.setdefault(str(run_id), []).append({
                            "action_type": action_type,
                            "payload": payload if isinstance(payload, dict) else {},
                            "result": result if isinstance(result, dict) else {},
                            "at": at.isoformat() if at else None,
                        })
        runs = []
        for (run_id, agent_type, status, triggered_by,
             output, error, started_at, completed_at) in run_rows:
            rid = str(run_id)
            runs.append({
                "id": rid,
                "agent_type": agent_type,
                "status": status,
                "triggered_by": triggered_by,
                "output": output if isinstance(output, dict) else {},
                "error": error,
                "started_at": started_at.isoformat() if started_at else None,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "actions": actions_by_run.get(rid, []),
            })
        return {"status": "success", "runs": runs}
    except Exception as e:
        main.logger.error(f"[cockpit/agents/runs] query failed for {person_id}: {e}")
        return {"status": "error", "detail": "Could not load agent runs."}


@router.get("/api/cockpit/agents/active")
def cockpit_agents_active(user: dict = main.Depends(main.require_cockpit_user)):
    """
    All currently running/pending agent runs across all persons — powers the
    Topbar AgentSystemStatus chip. Returns a lightweight list (no actions).
    """
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ar.id, ar.person_id, ar.agent_type, ar.status, "
                    "       ar.started_at, p.display_name "
                    "FROM agent_runs ar "
                    "JOIN person p ON p.id = ar.person_id "
                    "WHERE ar.status IN ('pending', 'running') "
                    "ORDER BY ar.started_at DESC",
                )
                rows = cur.fetchall()
        runs = [
            {
                "id": str(r[0]),
                "person_id": str(r[1]),
                "agent_type": r[2],
                "status": r[3],
                "started_at": r[4].isoformat() if r[4] else None,
                "person_name": r[5] or "Lead",
            }
            for r in rows
        ]
        return {"status": "success", "runs": runs, "count": len(runs)}
    except Exception as e:
        main.logger.error(f"[cockpit/agents/active] query failed: {e}")
        return {"status": "error", "detail": "Could not load active agents."}


@router.post("/api/cockpit/agents/trigger")
def cockpit_agents_trigger(
    body: main.AgentTriggerBody,
    background_tasks: main.BackgroundTasks,
    user: dict = main.Depends(main.require_cockpit_user),
):
    """
    Manually fire an agent for a person without touching the opportunity.

    The lead stays in the Work Queue; the AgentPip and Agent Log tab update
    live via Supabase Realtime as the run progresses. Designed for observation
    and debugging — the lead is never removed from the screen. Returns
    immediately (the agent runs in a BackgroundTask).
    """
    if body.agent_type != "qualification":
        raise main.HTTPException(status_code=400, detail=f"Unknown agent type {body.agent_type!r}.")

    by = user.get("email") or user.get("sub") or "operator"
    background_tasks.add_task(
        main.run_agent,
        agent_type="qualification",
        person_id=body.person_id,
        triggered_by="manual",
        agent_fn=main.qualification_agent,
        input_snapshot={"triggered_by_user": by},
    )
    main.logger.info(
        "[cockpit/agents/trigger] qualification agent queued for person=%s by=%s",
        body.person_id, by,
    )
    return {"status": "accepted", "person_id": body.person_id, "agent_type": body.agent_type}


@router.get("/api/cockpit/analytics")
def cockpit_analytics(user: dict = main.Depends(main.require_cockpit_user)):
    """
    Native Analytics for the cockpit Bento dashboard — NO Power BI embed. One
    payload aggregating the social tables (followers / posts / comments / likers)
    and the CRM funnel (opportunities / bookings); the frontend draws every chart
    natively (recharts, Atelier-themed).

    The headline community size is the operator-maintained figure in app_config
    (`analytics.community_size`) — the DB followers table is a partial scrape, so
    that one number is curated while every other figure is live SQL.
    """
    try:
        community_size = int(main._get_config("analytics.community_size") or 0)
    except (TypeError, ValueError):
        community_size = 0
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM followers")
                followers_tracked = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM posts")
                posts = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM likers")
                likes = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM comments")
                comments = cur.fetchone()[0]
                # Follower growth — cumulative tracked follows by week.
                cur.execute(
                    "SELECT to_char(date_trunc('week', followed_at), 'YYYY-MM-DD'), COUNT(*) "
                    "FROM followers WHERE followed_at IS NOT NULL GROUP BY 1 ORDER BY 1"
                )
                weekly = cur.fetchall()
                # Top posts by likes (shortcode + counts only — no caption column assumed).
                cur.execute(
                    "WITH lk AS (SELECT post_shortcode, COUNT(*) c FROM likers GROUP BY 1), "
                    "     cm AS (SELECT post_shortcode, COUNT(*) c FROM comments GROUP BY 1) "
                    "SELECT p.post_shortcode, COALESCE(lk.c, 0), COALESCE(cm.c, 0) "
                    "FROM posts p "
                    "LEFT JOIN lk ON lk.post_shortcode = p.post_shortcode "
                    "LEFT JOIN cm ON cm.post_shortcode = p.post_shortcode "
                    "ORDER BY COALESCE(lk.c, 0) DESC LIMIT 6"
                )
                top = cur.fetchall()
                # CRM funnel — open opportunities by stage.
                cur.execute(
                    "SELECT stage, COUNT(*) FROM opportunities WHERE closed_at IS NULL GROUP BY stage"
                )
                stage_rows = cur.fetchall()
                cur.execute("SELECT COUNT(*) FROM bookings")
                bookings = cur.fetchone()[0]

        running, growth = 0, []
        for wk, n in weekly:
            running += n
            growth.append({"week": wk, "followers": running})
        growth = growth[-12:]
        stages = {s: c for (s, c) in stage_rows}
        return {
            "status": "success",
            "community": {
                "size": community_size,
                "followers_tracked": followers_tracked,
                "likes": likes,
                "comments": comments,
                "posts": posts,
                "growth": growth,
                "top_posts": [
                    {"shortcode": sc, "likes": lk, "comments": cm}
                    for (sc, lk, cm) in top
                ],
            },
            "pipeline": [
                {"stage": s, "count": stages.get(s, 0)}
                for s in main.nexus_interactions.PIPELINE_STAGES
            ],
            "booked": bookings,
        }
    except Exception as e:
        main.logger.error(f"[cockpit/analytics] query failed: {e}")
        return {"status": "error", "detail": "Could not load analytics."}


@router.get("/api/cockpit/analytics/funnel")
def cockpit_analytics_funnel(
    user: dict = main.Depends(main.require_cockpit_user),
    days: main.Optional[int] = None,   # 7 | 30 | 90 | None = all-time
):
    """
    Conversion rates and velocity. Optional ?days=N limits to the last N days.

    Fix: 'engaged' ever_entered uses total opportunity count (leads are created as
    'engaged' by default — no stage_change interaction is logged for the initial state).
    For all other stages, interaction-based entry counts are accurate.
    """
    since_clause = "AND occurred_at >= NOW() - (%s * interval '1 day')" if days else ""
    since_args   = (days,) if days else ()
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                # Pair data — filter by date window when days is set
                if days:
                    # Simple count-only query for date-filtered view.
                    # Velocity (avg hours) requires nested window+aggregate which PostgreSQL
                    # disallows at the same query level — return NULL for those columns.
                    cur.execute(
                        "SELECT payload->>'from' AS from_stage, "
                        "       payload->>'to'   AS to_stage, "
                        "       COUNT(*)         AS transition_count, "
                        "       COUNT(DISTINCT person_id) AS unique_leads, "
                        "       NULL::numeric    AS total_entered_from_stage, "
                        "       NULL::numeric    AS conversion_pct, "
                        "       NULL::numeric    AS avg_hours_in_stage, "
                        "       NULL::numeric    AS median_hours_in_stage, "
                        "       MAX(occurred_at) AS last_transition_at "
                        "FROM interactions "
                        "WHERE kind = 'stage_change' "
                        "  AND payload->>'from' IS NOT NULL "
                        "  AND payload->>'to'   IS NOT NULL "
                        "  AND occurred_at >= NOW() - (%s * interval '1 day') "
                        "GROUP BY payload->>'from', payload->>'to' "
                        "ORDER BY payload->>'from', payload->>'to'",
                        (days,),
                    )
                else:
                    # All-time: query interactions directly (same logic as funnel_metrics
                    # materialized view) so we always get live data without waiting for
                    # the nightly REFRESH. The mat-view is empty until first refresh runs.
                    cur.execute(
                        "WITH entries AS ("
                        "  SELECT payload->>'to' AS stage,"
                        "         COUNT(DISTINCT person_id) AS entered_count"
                        "  FROM interactions"
                        "  WHERE kind='stage_change' AND payload->>'to' IS NOT NULL"
                        "  GROUP BY payload->>'to'"
                        "), "
                        "transitions AS ("
                        "  SELECT t.payload->>'from' AS from_stage,"
                        "         t.payload->>'to'   AS to_stage,"
                        "         COUNT(*)            AS transition_count,"
                        "         COUNT(DISTINCT t.person_id) AS unique_leads,"
                        "         AVG(EXTRACT(EPOCH FROM (t.occurred_at - entry.occurred_at)) / 3600.0)::NUMERIC(8,1) AS avg_hours_in_stage,"
                        "         PERCENTILE_CONT(0.5) WITHIN GROUP ("
                        "           ORDER BY EXTRACT(EPOCH FROM (t.occurred_at - entry.occurred_at)) / 3600.0"
                        "         )::NUMERIC(8,1) AS median_hours_in_stage,"
                        "         MAX(t.occurred_at) AS last_transition_at"
                        "  FROM interactions t"
                        "  LEFT JOIN LATERAL ("
                        "    SELECT occurred_at FROM interactions"
                        "    WHERE person_id = t.person_id AND kind='stage_change'"
                        "      AND payload->>'to' = t.payload->>'from'"
                        "      AND occurred_at < t.occurred_at"
                        "    ORDER BY occurred_at DESC LIMIT 1"
                        "  ) entry ON TRUE"
                        "  WHERE t.kind='stage_change'"
                        "    AND t.payload->>'from' IS NOT NULL"
                        "    AND t.payload->>'to'   IS NOT NULL"
                        "  GROUP BY t.payload->>'from', t.payload->>'to'"
                        ") "
                        "SELECT tr.from_stage, tr.to_stage, tr.transition_count, tr.unique_leads,"
                        "       e.entered_count,"
                        "       ROUND(tr.unique_leads::NUMERIC / NULLIF(e.entered_count,0) * 100, 1),"
                        "       tr.avg_hours_in_stage, tr.median_hours_in_stage, tr.last_transition_at"
                        " FROM transitions tr"
                        " LEFT JOIN entries e ON e.stage = tr.from_stage"
                        " ORDER BY tr.from_stage, tr.to_stage"
                    )
                pair_rows = cur.fetchall()
                main.logger.info(f"[cockpit/analytics/funnel] pair_rows={len(pair_rows)} days={days}")

                # Per-stage entry counts from interactions (excludes initial 'engaged')
                cur.execute(
                    "SELECT payload->>'to' AS stage, COUNT(DISTINCT person_id) AS entered "
                    "FROM interactions "
                    f"WHERE kind = 'stage_change' AND payload->>'to' IS NOT NULL {since_clause}"
                    "GROUP BY payload->>'to'",
                    since_args,
                )
                entry_rows = cur.fetchall()

                # 'engaged' special case: total all-time opportunity count is the true entry
                # (opportunities are created at 'engaged' — no stage_change recorded for it).
                if days:
                    cur.execute(
                        "SELECT COUNT(DISTINCT person_id) FROM opportunities "
                        "WHERE created_at >= NOW() - (%s * interval '1 day')",
                        (days,),
                    )
                else:
                    cur.execute("SELECT COUNT(DISTINCT person_id) FROM opportunities")
                engaged_total = cur.fetchone()[0]
                main.logger.info(f"[cockpit/analytics/funnel] entry_rows={entry_rows} engaged_total={engaged_total}")

                # Current open counts per stage
                cur.execute(
                    "SELECT stage, COUNT(*) FROM opportunities "
                    "WHERE closed_at IS NULL GROUP BY stage"
                )
                open_rows = cur.fetchall()

        pairs = [
            {
                "from_stage":               r[0],
                "to_stage":                 r[1],
                "transition_count":         r[2],
                "unique_leads":             r[3],
                "total_entered_from_stage": r[4],
                "conversion_pct":           float(r[5]) if r[5] is not None else None,
                "avg_hours_in_stage":       float(r[6]) if r[6] is not None else None,
                "median_hours_in_stage":    float(r[7]) if r[7] is not None else None,
                "last_transition_at":       r[8].isoformat() if r[8] else None,
            }
            for r in pair_rows
        ]
        entries     = {r[0]: r[1] for r in entry_rows}
        open_counts = {r[0]: r[1] for r in open_rows}
        # 'engaged' has no stage_change INTO it (leads start there), so the CTE
        # can't compute entered_count or conversion_pct for engaged→* pairs.
        # Patch both using engaged_total from the opportunities count.
        entries["engaged"] = engaged_total
        if engaged_total:
            for p in pairs:
                if p["from_stage"] == "engaged" and p["conversion_pct"] is None:
                    p["total_entered_from_stage"] = int(engaged_total)
                    p["conversion_pct"] = round(
                        float(p["unique_leads"]) / float(engaged_total) * 100, 1
                    )

        stages = [
            {
                "stage":        s,
                "ever_entered": entries.get(s, 0),
                "open_now":     open_counts.get(s, 0),
            }
            for s in main.nexus_interactions.PIPELINE_STAGES
        ]

        return {"status": "success", "pairs": pairs, "stages": stages, "days": days}
    except Exception as e:
        main.logger.error(f"[cockpit/analytics/funnel] query failed: {e}")
        return {"status": "error", "detail": "Could not load funnel data."}


@router.get("/api/cockpit/analytics/sla")
def cockpit_analytics_sla(user: dict = main.Depends(main.require_cockpit_user)):
    """
    Per-lead SLA status — accountability-based (migration 004).

    Fix: person_name falls back to wa_ref_code when display_name is NULL.
    Sort + display now key off hours_since_touch (accountable_since), not
    hours_in_stage — stage age climbs even while the operator is actively
    working a lead, so it no longer drives the truth or the ordering.
    """
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                # Join against person to get wa_ref_code fallback for unnamed leads
                cur.execute(
                    "SELECT s.opportunity_id, s.person_id, "
                    "       COALESCE(s.person_name, 'Lead ' || p.wa_ref_code, 'Lead') AS person_name, "
                    "       s.stage, s.stage_entered_at, s.hours_in_stage, "
                    "       s.target_hours, s.warn_hours, s.sla_status, "
                    "       s.hours_since_touch, s.waiting_on "
                    "FROM lead_sla_status s "
                    "JOIN person p ON p.id = s.person_id AND p.tenant_id = %(t)s "
                    "ORDER BY "
                    "  CASE s.sla_status WHEN 'breach' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, "
                    "  s.hours_since_touch DESC NULLS LAST",
                    {"t": main.nexus_ai_planner.DEFAULT_TENANT_ID},
                )
                rows = cur.fetchall()

        leads = [
            {
                "opportunity_id":    str(r[0]),
                "person_id":         str(r[1]),
                "person_name":       r[2],
                "stage":             r[3],
                "stage_entered_at":  r[4].isoformat() if r[4] else None,
                "hours_in_stage":    float(r[5]) if r[5] is not None else None,
                "target_hours":      r[6],
                "warn_hours":        r[7],
                "sla_status":        r[8] or "unknown",
                "hours_since_touch": float(r[9]) if r[9] is not None else None,
                "waiting_on":        r[10] or "untouched",
            }
            for r in rows
        ]
        summary = {
            "breach":  sum(1 for l in leads if l["sla_status"] == "breach"),
            "warn":    sum(1 for l in leads if l["sla_status"] == "warn"),
            "ok":      sum(1 for l in leads if l["sla_status"] == "ok"),
            "unknown": sum(1 for l in leads if l["sla_status"] == "unknown"),
            "total":   len(leads),
        }
        return {"status": "success", "leads": leads, "summary": summary}
    except Exception as e:
        main.logger.error(f"[cockpit/analytics/sla] query failed: {e}")
        return {"status": "error", "detail": "Could not load SLA data."}


@router.post("/api/cockpit/ai/chat")
def cockpit_ai_chat(
    body: main._AiChatBody,
    user: dict = main.Depends(main.require_cockpit_user),
):
    """
    NLP brain for the cockpit AI assistant — tool-use query planner.

    Call 1 (plan): the LLM sees the nexus.ai_planner tool catalog and returns a
    strict-JSON plan — tool names + typed args only, never SQL. The plan is
    parsed defensively and validated; ANY failure falls back to the legacy
    chip router so the endpoint cannot go dark. Kill switch: set app_config
    `ai_chat.planner_enabled` to "false" to force the legacy path.

    Execute: validated steps run parameter-bound inside a read-only
    transaction, every query tenant-scoped and LIMIT'd.

    Call 2 (reply): the LLM answers grounded in the fetched blocks only.
    intent / context_data / actions — the frozen frontend contract — are
    assembled deterministically in Python, never by the model.
    """
    msg   = body.message.strip()
    chips = [c.strip() for c in body.chips if c.strip()]

    if not msg and not chips:
        return {
            "status": "error", "reply": "Please enter a question.",
            "intent": "general", "context_data": None, "actions": main._AI_ACTIONS["general"],
        }

    planner_enabled = main._get_config("ai_chat.planner_enabled").strip().lower() != "false"
    results = None
    if planner_enabled:
        try:
            plan_raw = main._call_llm(
                main.nexus_ai_planner.build_planner_prompt(msg, chips, body.history)
            )
            plan    = main.nexus_ai_planner.parse_plan(main._parse_llm_json(plan_raw))
            results = main._execute_ai_plan(plan)
            main.logger.info(
                f"[cockpit/ai/chat] planner plan={[s.tool for s in plan]} "
                f"executed={len(results)}"
            )
        except Exception as plan_err:
            main.logger.warning(
                f"[cockpit/ai/chat] planner failed → legacy fallback: {plan_err}"
            )
            results = None

    if results is not None:
        context_blocks = [r.context_block for r in results]
        primary_intent, ctx_data = main.nexus_ai_planner.resolve_contract(results)
    else:
        chips, context_blocks, primary_intent, ctx_data = main._legacy_ai_chat_context(msg, chips)

    full_prompt = main.nexus_ai_planner.build_reply_prompt(msg, chips, body.history, context_blocks)

    main.logger.info(f"[cockpit/ai/chat] chips={len(chips)} context_blocks={len(context_blocks)} "
                f"msg_len={len(msg)} intent={primary_intent}")

    # ── Call the reply LLM ────────────────────────────────────────────────────
    # Resolve action list: try specific intent variant (e.g. sla_lead_breach),
    # then base intent (e.g. sla_lead), then general fallback.
    actions = (
        main._AI_ACTIONS.get(primary_intent)
        or main._AI_ACTIONS.get(primary_intent.rsplit("_", 1)[0])
        or main._AI_ACTIONS["general"]
    )

    try:
        reply = main._call_llm(full_prompt)
        return {
            "status":       "success",
            "reply":        reply,
            "intent":       primary_intent,
            "context_data": ctx_data,
            "actions":      actions,
        }
    except TimeoutError:
        return {
            "status": "error",
            "reply":  "The AI took too long to respond — please try again in a moment.",
            "intent": "general", "context_data": None, "actions": main._AI_ACTIONS["general"],
        }
    except Exception as llm_err:
        err_s = str(llm_err).lower()
        if "429" in err_s or "quota" in err_s or "resource_exhausted" in err_s:
            return {
                "status": "error",
                "reply":  "The AI is temporarily busy — please wait ~30 seconds and retry.",
                "intent": "general", "context_data": None, "actions": main._AI_ACTIONS["general"],
            }
        main.logger.error(f"[cockpit/ai/chat] LLM error: {llm_err}", exc_info=True)
        return {
            "status": "error",
            "reply":  "Something went wrong. Please try again.",
            "intent": "general", "context_data": None, "actions": main._AI_ACTIONS["general"],
        }


@router.post("/api/cockpit/whatsapp/draft")
def cockpit_whatsapp_draft(
    body: main._WaDraftBody,
    user: dict = main.Depends(main.require_cockpit_user),
):
    """
    Generate a personalised Hebrew WhatsApp draft for a lead, using:
      • Person-360 (name / stage / essence / goal / tension)
      • WhatsApp conversation thread (last 30 messages)
      • Copilot persona + drafting rules (Israeli Hebrew, short, eye-level)

    Returns the draft text + the lead's WhatsApp phone number so the frontend
    can open wa.me/{phone}?text={draft} in a new tab.
    """
    person_id = body.person_id.strip()
    if not person_id:
        return {"status": "error", "detail": "person_id is required."}

    try:
        with main.get_db_conn() as conn:
            # ── Person-360 ────────────────────────────────────────────────────
            person = main._db_person360(conn, person_id)
            if not person:
                return {"status": "error", "detail": "Lead not found."}

            # ── WhatsApp thread (last 30 messages) ───────────────────────────
            thread = main._db_person_thread(conn, person_id, limit=30)

            # ── WhatsApp phone number ─────────────────────────────────────────
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT external_id FROM person_identity "
                    "WHERE person_id = %s AND channel = 'whatsapp' LIMIT 1",
                    (person_id,),
                )
                pi_row = cur.fetchone()
            wa_phone = pi_row[0] if pi_row else None

        # ── Build the draft prompt ───────────────────────────────────────────
        # The Copilot PERSONA + DRAFTING_RULES already mandate short Hebrew text.
        # Re-state the language requirement in the intent instruction so Gemini
        # can't drift to English even when person data is sparse.
        stage_label = (person.get("stage") or "unknown stage").capitalize()
        intent = (
            f"WRITE IN HEBREW ONLY (עברית בלבד). "
            f"הלקוח נמצא בשלב {stage_label} ולא הגיב זמן רב. "
            f"כתוב הודעת מעקב קצרה (1-3 משפטים), אנושית ואישית. "
            f"המטרה: להחזיר את הלקוח לשיחה ולקדם לשלב הבא."
        )
        prompt = main.nexus_copilot.build_draft_prompt(person, thread, intent=intent)

        draft = main._call_llm(prompt)
        main.logger.info(
            f"[cockpit/whatsapp/draft] person={person_id!r} "
            f"has_phone={wa_phone is not None} draft_len={len(draft)}"
        )
        return {
            "status":      "success",
            "draft":       draft,
            "wa_phone":    wa_phone or "",
            "person_name": person.get("name") or "Lead",
        }

    except TimeoutError:
        return {"status": "error", "detail": "The AI took too long — please try again."}
    except Exception as e:
        main.logger.error(f"[cockpit/whatsapp/draft] error for {person_id!r}: {e}", exc_info=True)
        return {"status": "error", "detail": "Could not generate draft."}


@router.post("/api/cockpit/whatsapp/phone")
def cockpit_whatsapp_phone(
    body: main._WaPhoneBody,
    user: dict = main.Depends(main.require_cockpit_user),
):
    """Save / update a lead's WhatsApp phone number in person_identity."""
    person_id = body.person_id.strip()
    if not person_id:
        return {"status": "error", "detail": "person_id is required."}

    wa_phone = main._normalize_wa_phone(body.phone)
    if not wa_phone:
        return {
            "status": "error",
            "detail": "That doesn't look like a valid phone number.",
        }

    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                # Guard: the person must exist (FK would fail anyway, but a clean
                # message beats a 500).
                cur.execute("SELECT 1 FROM person WHERE id = %s", (person_id,))
                if cur.fetchone() is None:
                    return {"status": "error", "detail": "Lead not found."}

                # Check-then-write (no unique index to ON CONFLICT on).
                cur.execute(
                    "SELECT id FROM person_identity "
                    "WHERE person_id = %s AND channel = 'whatsapp' LIMIT 1",
                    (person_id,),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE person_identity SET external_id = %s WHERE id = %s",
                        (wa_phone, existing[0]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO person_identity (person_id, channel, external_id, confidence) "
                        "VALUES (%s, 'whatsapp', %s, 'operator_entered')",
                        (person_id, wa_phone),
                    )
                conn.commit()

        main.logger.info(f"[cockpit/whatsapp/phone] saved {wa_phone} for person={person_id!r}")
        return {"status": "success", "wa_phone": wa_phone}

    except Exception as e:
        main.logger.error(f"[cockpit/whatsapp/phone] error for {person_id!r}: {e}", exc_info=True)
        return {"status": "error", "detail": "Could not save the phone number."}


@router.post("/api/cockpit/whatsapp/outreach")
def cockpit_whatsapp_outreach(
    body: main._WaOutreachBody,
    user: dict = main.Depends(main.require_cockpit_user),
):
    """Log an operator outreach-click so the accountability SLA clock resets."""
    person_id = body.person_id.strip()
    if not person_id:
        return {"status": "error", "detail": "person_id is required."}

    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM person WHERE id = %s", (person_id,))
                if cur.fetchone() is None:
                    return {"status": "error", "detail": "Lead not found."}
                # Resolve the open opportunity for payload context (optional).
                cur.execute(
                    "SELECT id FROM opportunities "
                    "WHERE person_id = %s AND closed_at IS NULL "
                    "ORDER BY stage_entered_at DESC NULLS LAST LIMIT 1",
                    (person_id,),
                )
                opp = cur.fetchone()
                opportunity_id = str(opp[0]) if opp else None

            # Idempotent per-minute: double-clicks collapse via dedup_key
            # (interactions_dedup_uniq partial unique index + ON CONFLICT DO NOTHING).
            minute_bucket = int(main.time.time() // 60)
            preview = (body.draft_preview or "").strip()[:120]
            written = main.nexus_interactions.log_interaction(
                conn, "outreach_click", "whatsapp",
                person_id=person_id,
                payload={
                    "via": "wa.me",
                    "by": "operator",
                    "opportunity_id": opportunity_id,
                    "draft_preview": preview,
                },
                dedup_key=f"outreach:{person_id}:{minute_bucket}",
                source="cockpit",
            )
            conn.commit()

        main.logger.info(f"[cockpit/whatsapp/outreach] person={person_id!r} logged={written}")
        return {"status": "success", "logged": written}

    except Exception as e:
        main.logger.error(f"[cockpit/whatsapp/outreach] error for {person_id!r}: {e}", exc_info=True)
        return {"status": "error", "detail": "Could not log outreach."}


@router.post("/api/cockpit/thread/{person_id}/send")
def cockpit_thread_send(person_id: str, body: main.ThreadSendBody,
                        user: dict = main.Depends(main.require_cockpit_user)):
    """
    One Thread — send a message from the cockpit composer. Supports WhatsApp,
    Instagram, and Telegram; an unrecognized channel returns
    'channel_not_supported' rather than silently no-op'ing or sending on the
    wrong rail. Always 200 with a structured body — the composer needs
    reason_code to explain *why* a send was blocked, not a bare error.
    """
    channel = (body.channel or "whatsapp").strip().lower()
    by = user.get("email") or user.get("sub") or "operator"

    if channel not in main._SUPPORTED_SEND_CHANNELS:
        # Fast-fail before touching the DB — route_and_send would reject this
        # too, but there's no reason to pay a round-trip for a client error.
        return {"status": "error", "reason_code": "channel_not_supported",
                "detail": f"Sending on {channel} isn't available yet."}

    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM person WHERE id = %s", (person_id,))
                if cur.fetchone() is None:
                    return {"status": "error", "reason_code": "not_found",
                            "detail": "Lead not found."}

            result = main.route_and_send(conn, person_id, channel, body.body, by=by,
                                    client_token=body.client_token)
            if result["ok"]:
                conn.commit()
                return {"status": "success", "message": result["message"],
                        "deduped": result.get("deduped", False)}
            conn.rollback()
            return {"status": "error", "reason_code": result["reason_code"],
                    "detail": result["detail"]}

    except Exception as e:
        main.logger.error(f"[cockpit/thread/send] failed for {person_id!r}: {e}", exc_info=True)
        return {"status": "error", "reason_code": "internal_error",
                "detail": "Could not send the message."}


@router.get("/api/cockpit/search")
def cockpit_search(q: str = "", user: dict = main.Depends(main.require_cockpit_user)):
    """
    Unified search across People (open opportunities) and Content pieces.
    Pages are static and filtered client-side; only server-side data lives here.

    Returns up to 8 people matches and 5 content matches, ordered by recency.
    Minimum 2 characters required — returns empty results otherwise to avoid
    scanning the full table on every keystroke.
    """
    q = q.strip()
    if len(q) < 2:
        return {"results": []}

    _CHANNEL: dict[str, str] = {
        "whatsapp": "WhatsApp", "telegram": "Telegram",
        "instagram": "Instagram", "web": "Web",
    }
    _STAGE: dict[str, str] = {
        "captured": "captured", "qualified": "qualified",
        "price_offered": "price offered", "booked": "booked",
    }

    results = []
    pattern = f"%{q}%"

    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                # ── People: search display_name across open opportunities ──────────
                cur.execute(
                    "SELECT DISTINCT ON (p.id) "
                    "       o.id, p.display_name, o.source_channel, o.stage "
                    "FROM person p "
                    "JOIN opportunities o ON o.person_id = p.id AND o.closed_at IS NULL "
                    "  AND (o.snoozed_until IS NULL OR o.snoozed_until <= NOW()) "
                    "WHERE p.display_name ILIKE %s "
                    "ORDER BY p.id, o.created_at DESC "
                    "LIMIT 8",
                    (pattern,),
                )
                for row in cur.fetchall():
                    opp_id, display_name, channel, stage = row
                    ch = _CHANNEL.get(channel or "", channel or "")
                    st = _STAGE.get(stage or "", stage or "")
                    results.append({
                        "type": "person",
                        "id": str(opp_id),
                        "label": display_name or "Unknown",
                        "sublabel": f"{ch} · {st}",
                        "route": f"/app/queue?focus={opp_id}",
                    })

                # ── Content: search by title ──────────────────────────────────────
                cur.execute(
                    "SELECT id, title, status FROM content_pieces "
                    "WHERE title ILIKE %s "
                    "ORDER BY updated_at DESC LIMIT 5",
                    (pattern,),
                )
                for row in cur.fetchall():
                    piece_id, title, status = row
                    results.append({
                        "type": "content",
                        "id": str(piece_id),
                        "label": title or "Untitled piece",
                        "sublabel": status or "idea",
                        "route": f"/app/content?piece={piece_id}",
                    })

    except Exception as e:
        main.logger.warning("[search] query failed: %s", e)
        return {"results": []}

    return {"results": results}


@router.get("/api/cockpit/content")
def cockpit_content_list(user: dict = main.Depends(main.require_cockpit_user)):
    """All content pieces, newest-touched first — for the Studio rail + canvas."""
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {main._CONTENT_COLS} FROM content_pieces "
                    "ORDER BY updated_at DESC"
                )
                rows = cur.fetchall()
        return {"status": "success", "items": [main._content_row(r) for r in rows]}
    except Exception as e:
        main.logger.error(f"[cockpit/content] list failed: {e}")
        return {"status": "error", "detail": "Could not load content."}


@router.post("/api/cockpit/content")
def cockpit_content_create(body: main.ContentCreate, user: dict = main.Depends(main.require_cockpit_user)):
    status = body.status if body.status in main._CONTENT_STATUSES else "idea"
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO content_pieces (title, body, status, theme_tags) "
                    f"VALUES (%s, %s, %s, %s) RETURNING {main._CONTENT_COLS}",
                    (body.title, body.body, status, body.theme_tags),
                )
                row = cur.fetchone()
            conn.commit()
        return {"status": "success", "item": main._content_row(row)}
    except Exception as e:
        main.logger.error(f"[cockpit/content] create failed: {e}")
        return {"status": "error", "detail": "Could not create the piece."}


@router.patch("/api/cockpit/content/{piece_id}")
def cockpit_content_update(piece_id: str, body: main.ContentUpdate,
                          user: dict = main.Depends(main.require_cockpit_user)):
    fields = body.model_dump(exclude_unset=True)   # only what the client sent
    if "status" in fields and fields["status"] not in main._CONTENT_STATUSES:
        raise main.HTTPException(status_code=400, detail="Invalid status.")
    allowed = {"title", "body", "status", "theme_tags", "leads_attributed"}
    sets, params = [], []
    for key, val in fields.items():
        if key in allowed:                          # column names are whitelisted
            sets.append(f"{key} = %s")
            params.append(val)
    if not sets:
        raise main.HTTPException(status_code=400, detail="No fields to update.")
    # Stamp published_at the first time a piece goes live.
    extra = ", published_at = COALESCE(published_at, NOW())" if fields.get("status") == "published" else ""
    params.append(piece_id)
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE content_pieces SET {', '.join(sets)}, updated_at = NOW(){extra} "
                    f"WHERE id = %s RETURNING {main._CONTENT_COLS}",
                    params,
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise main.HTTPException(status_code=404, detail="Piece not found.")
        return {"status": "success", "item": main._content_row(row)}
    except main.HTTPException:
        raise
    except Exception as e:
        main.logger.error(f"[cockpit/content] update failed: {e}")
        return {"status": "error", "detail": "Could not save the piece."}


@router.delete("/api/cockpit/content/{piece_id}")
def cockpit_content_delete(piece_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM content_pieces WHERE id = %s", (piece_id,))
                deleted = cur.rowcount
            conn.commit()
        return {"status": "success", "deleted": deleted}
    except Exception as e:
        main.logger.error(f"[cockpit/content] delete failed: {e}")
        return {"status": "error", "detail": "Could not delete the piece."}
