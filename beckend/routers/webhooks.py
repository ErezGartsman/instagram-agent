"""
routers.webhooks — channel webhooks (Telegram / Instagram / WhatsApp / Kapso /
Calendly), moved VERBATIM from main.py (E0 strangler extraction).

Same late-binding contract as routers.cockpit: all helpers resolve through
main.<name> at call time — tests' patch("main.X") and future helper migration
both keep working. Mounted at the bottom of main.py.
"""
from fastapi import APIRouter

import main

router = APIRouter()

@router.post("/api/webhook/telegram")
def telegram_webhook(
    update: dict = main.Body(default={}),
    x_telegram_bot_api_secret_token: main.Optional[str] = main.Header(default=None),
):
    """
    Telegram Bot webhook — the RAG "Erez representative".

    Defined as a sync `def` so FastAPI runs it in a worker thread: the blocking
    DB / embedding / LLM / urllib calls below never stall the event loop.

    Auth: Telegram cannot send our Bearer token, so this route is deliberately
    NOT behind require_auth. Instead we verify the secret token Telegram echoes
    in the X-Telegram-Bot-Api-Secret-Token header (configured via
    setWebhook?secret_token=…). Until the secret is set the check is skipped so
    local testing stays friction-free.

    The handler always returns 200 {"ok": true}; user-facing problems are
    delivered as chat replies rather than HTTP errors, so Telegram never retries.
    """
    # ── 1. Verify the shared secret ───────────────────────────────────────────
    if main.settings.telegram_webhook_secret:
        if not main._secret_eq(x_telegram_bot_api_secret_token, main.settings.telegram_webhook_secret):
            main.logger.warning("[telegram] Rejected webhook: bad/missing secret token.")
            return {"ok": True}   # 200, but do nothing

    # ── 2. Parse the incoming update ─────────────────────────────────────────
    message = update.get("message") or update.get("edited_message") or {}
    chat    = message.get("chat") or {}
    chat_id = chat.get("id")

    if chat_id is None:
        return {"ok": True}   # channel post, callback_query, etc. — ignore
    chat_id_str = str(chat_id)

    # ── 2a. Native contact share (button tap or manual share) ─────────────────
    # This branch runs BEFORE the text branch.  When a user taps the
    # contact-share keyboard button, Telegram delivers message.contact
    # (not message.text), so we capture it here and never reach the text path.
    contact = message.get("contact")
    if contact:
        phone     = (contact.get("phone_number") or "").strip()
        first     = contact.get("first_name") or ""
        last      = contact.get("last_name")  or ""
        name      = f"{first} {last}".strip() or None

        if phone:
            try:
                with main.get_db_conn() as conn:
                    session_id     = main._db_get_or_create_telegram_session(conn, chat_id_str)
                    history        = main._db_load_history(conn, session_id, limit=12)
                    intent_summary = main._build_intent_summary(history, "")
                    lead_id        = main._db_save_lead(
                        conn, session_id, chat_id_str, name, phone, intent_summary
                    )
                    conn.commit()

                # Warm confirmation FIRST so the user gets instant feedback —
                # the slow owner-alert + CRM sync must never delay it (P1).
                main._send_telegram_message(chat_id, main._format_lead_thanks(name),
                                       reply_markup=main._REMOVE_KEYBOARD)
                if lead_id:
                    # Owner alert + CRM sync + bookkeeping (best-effort, post-ack).
                    main._finalize_lead(lead_id, name, phone, intent_summary, chat_id_str)
                    main._audit("lead_captured", chat_id=chat_id_str,
                           lead_id=lead_id, phone_len=len(phone))
                else:
                    main.logger.info(f"[leads] Duplicate contact from {chat_id_str} — skipped.")
            except Exception as e:
                main.logger.error(f"[leads] Contact capture failed: {e}", exc_info=True)
                main._send_telegram_message(chat_id, main._TG_ERROR,
                                       reply_markup=main._REMOVE_KEYBOARD)
        return {"ok": True}

    # ── 2b. Parse text ────────────────────────────────────────────────────────
    # Fall back to a photo/document caption so a user who types their question in
    # an image caption is understood instead of being told "text only".
    text = (message.get("text") or message.get("caption") or "").strip()

    if not text:
        main._send_telegram_message(chat_id, main._TG_NON_TEXT)   # sticker / voice / image w/o caption
        return {"ok": True}
    # ── Explicit commands are the ONLY way to exit a funnel state ─────────────
    # In a funnel (e.g. awaiting_qualification) free text is always treated as
    # the user's answer — never as a cancellation — so the deliberate /start and
    # /cancel commands are the sole, unambiguous escape hatch. Both reset state.
    if text.startswith("/start"):
        main._tg_clear_state(chat_id_str)
        main._send_telegram_message(
            chat_id,
            main._get_config("telegram.greeting") + main._config_suffix("disclosure.line"))
        return {"ok": True}
    if text.startswith("/cancel"):
        main._tg_clear_state(chat_id_str)
        main._send_telegram_message(chat_id, main._TG_ESCAPE_RESPONSE)
        main._audit("telegram_cancel_command", chat_id=chat_id_str)
        return {"ok": True}

    # ── Crisis check — always first among text handlers ───────────────────────
    # The empathetic response is delivered BEFORE any DB work so that a DB
    # hiccup can never block it. State is then cleared so the user returns to
    # a clean conversation after speaking with a professional — not the contact
    # keyboard or the qualification question.
    if main.is_crisis(text):
        main._audit("telegram_crisis", chat_id=chat_id_str)
        main._send_telegram_message(chat_id, main._get_config("crisis.message"))
        main._tg_clear_state(chat_id_str)   # best-effort; never blocks the crisis reply
        return {"ok": True}

    main._audit("telegram_request", chat_id=chat_id_str, question=main._redact_text(text))

    # ── 3. Rate limit (in-memory — runs before DB checkout) ───────────────────
    try:
        main.check_rate_limit(chat_id_str)
    except main.RateLimitError:
        main._send_telegram_message(chat_id, main._TG_RATE_LIMIT)
        return {"ok": True}

    # ── 4. Identity mapping — before validate_question so bot_state can
    #       bypass the length guard for short replies like "כן" (2 chars). ─────
    try:
        with main.get_db_conn() as conn:
            session_id   = main._db_get_or_create_telegram_session(conn, chat_id_str)
            bot_state    = main._db_get_session_state(conn, session_id)
            already_lead = main._db_has_lead(conn, chat_id_str)
            history      = main._db_load_history(conn, session_id, limit=12)
            conn.commit()

        # ── STATE: awaiting_qualification — capture the story (empathy-first) ──
        # CRITICAL UX INVARIANT: the user was just asked to share what they want
        # to talk about. ANY free text is their answer — however long, emotional,
        # or full of negative words ("הוא לא נתן לי סיבה", "I'll never trust").
        # This is intentionally handled BEFORE the escape gate and the moderation
        # guard so a genuine, raw story can never be misread as a cancellation or
        # rejected as "inappropriate". The ONLY way out of this state is the
        # explicit /start or /cancel command (handled above).
        if bot_state == "awaiting_qualification":
            if not already_lead:
                with main.get_db_conn() as conn:
                    main._db_save_message(conn, session_id, "user", text)
                    main._db_set_session_state(conn, session_id, main._make_contact_state(0))
                    main._db_touch_session(conn, session_id)
                    conn.commit()
                main._send_contact_keyboard(chat_id, main._TG_QUALIFICATION_ACK)
                main._audit("telegram_qualification_answered", chat_id=chat_id_str,
                       session_id=session_id)
                # NEXUS C2 — best-effort, never raises (see nexus/hooks.py).
                main.nexus_hooks.on_funnel_event(
                    "qualified", "telegram", session_id=session_id,
                    stage="qualified", dedup_key=f"qualified:{session_id}")
                return {"ok": True}
            # Already a lead — nothing to capture; clear stale state and continue
            # to normal conversation below.
            with main.get_db_conn() as conn:
                main._db_set_session_state(conn, session_id, None)
                conn.commit()
            bot_state = None

        # ── STATE: offered_meeting — interpret the reply to our consultation offer ─
        # The bot offered a meeting last turn. We classify the reply IN CONTEXT
        # (LLM-driven, natural-language-robust — see _bot_classify_offer_response)
        # and the STATE MACHINE acts: this is what makes a casual "אשמח" reliably
        # enter the funnel instead of the LLM hallucinating a closure. Handled
        # before the escape gate / moderation so a raw reply is never mishandled.
        if main._is_offered_meeting(bot_state):
            if already_lead:
                with main.get_db_conn() as conn:
                    main._db_set_session_state(conn, session_id, None)
                    conn.commit()
                bot_state = None   # already captured — fall through to normal chat
            else:
                decision, offer_reply = main._bot_classify_offer_response(text, history)

                if decision == "AFFIRM":
                    # Code (not the LLM) opens the funnel: show the contact keyboard.
                    with main.get_db_conn() as conn:
                        main._db_save_message(conn, session_id, "user", text)
                        main._db_set_session_state(conn, session_id, main._make_contact_state(0))
                        main._db_touch_session(conn, session_id)
                        conn.commit()
                    main._send_contact_keyboard(chat_id, main._TG_OFFER_ACK)
                    main._audit("telegram_offer_accepted", chat_id=chat_id_str,
                           session_id=session_id)
                    # NEXUS C3 — best-effort, never raises.
                    main.nexus_hooks.on_funnel_event(
                        "qualified", "telegram", session_id=session_id,
                        stage="qualified", dedup_key=f"qualified:{session_id}")
                    return {"ok": True}

                if decision == "DECLINE":
                    with main.get_db_conn() as conn:
                        main._db_save_message(conn, session_id, "user", text)
                        main._db_set_session_state(conn, session_id, None)
                        main._db_touch_session(conn, session_id)
                        conn.commit()
                    main._send_telegram_message(chat_id, main._TG_OFFER_DECLINED)
                    main._audit("telegram_offer_declined", chat_id=chat_id_str,
                           session_id=session_id)
                    return {"ok": True}

                # OTHER (question / hesitation / more sharing): warm reply + ONE
                # more soft offer, until the re-offer cap — then back off so we
                # never nag.
                count = main._parse_offer_count(bot_state)
                with main.get_db_conn() as conn:
                    main._db_save_message(conn, session_id, "user", text)
                    if count + 1 < main._MAX_REOFFERS:
                        out = (f"{offer_reply}\n\n{main._TG_MEETING_CTA}".strip()
                               if offer_reply else main._TG_MEETING_CTA)
                        main._db_set_session_state(conn, session_id,
                                              main._make_offer_state(count + 1))
                    else:
                        out = offer_reply or main._TG_OFFER_BACKOFF
                        main._db_set_session_state(conn, session_id, None)
                    main._db_save_message(conn, session_id, "assistant", out)
                    main._db_touch_session(conn, session_id)
                    conn.commit()
                main._send_telegram_message(chat_id, out)
                main._audit("telegram_offer_other", chat_id=chat_id_str,
                       session_id=session_id, reoffers=count + 1)
                return {"ok": True}

        # ── Escape-intent gate (short opt-outs only; awaiting_contact etc.) ────
        # A SHORT opt-out ("לא", "בטל", "stop") while still in a funnel state
        # clears it gracefully. awaiting_qualification is already handled above,
        # so this primarily serves awaiting_contact. The word-count guard inside
        # _is_escape_intent guarantees a long emotional message is never treated
        # as an opt-out here either. Checked before validate_question so a 2-char
        # "לא" isn't rejected by the length guard first.
        if bot_state and main._is_escape_intent(text):
            with main.get_db_conn() as conn:
                main._db_set_session_state(conn, session_id, None)
                conn.commit()
            main._send_telegram_message(chat_id, main._TG_ESCAPE_RESPONSE)
            main._audit("telegram_escape", chat_id=chat_id_str, prior_state=bot_state)
            return {"ok": True}

        # ── STATE: awaiting_contact ────────────────────────────────────────────
        # The contact keyboard was shown.  User must EITHER tap the native button
        # (handled as message.contact above) OR type their phone number.
        # Non-phone text gets a re-show with a retry counter; after
        # _MAX_CONTACT_RETRIES it exits gracefully.
        # Runs BEFORE validate_question so short replies ("כן", 2 chars) bypass
        # the length guard without producing a confusing error.
        if main._is_awaiting_contact(bot_state):
            phone = main._extract_phone_from_text(text)
            retry = main._parse_contact_retry(bot_state)

            if already_lead:
                # Lead captured since the keyboard was shown — clear stale state.
                with main.get_db_conn() as conn:
                    main._db_set_session_state(conn, session_id, None)
                    conn.commit()
                bot_state = None   # fall through to normal conversation
            elif phone:
                try:
                    intent_summary = main._build_intent_summary(history, text)
                    with main.get_db_conn() as conn:
                        lead_id = main._db_save_lead(conn, session_id, chat_id_str,
                                                None, phone, intent_summary)
                        main._db_set_session_state(conn, session_id, None)
                        conn.commit()
                    if lead_id:
                        # Confirm first (instant ack), then sync (P1).
                        main._send_telegram_message(chat_id, main._format_lead_thanks(None),
                                               reply_markup=main._REMOVE_KEYBOARD)
                        main._finalize_lead(lead_id, None, phone, intent_summary, chat_id_str)
                        main._audit("lead_captured_regex_awaiting", chat_id=chat_id_str,
                               lead_id=lead_id)
                except Exception as e:
                    main.logger.error(f"[leads] awaiting_contact capture: {e}", exc_info=True)
                    main._send_telegram_message(chat_id, main._TG_ERROR, reply_markup=main._REMOVE_KEYBOARD)
                return {"ok": True}
            elif retry >= main._MAX_CONTACT_RETRIES:
                # Graceful exit after three non-phone, non-escape replies.
                with main.get_db_conn() as conn:
                    main._db_set_session_state(conn, session_id, None)
                    conn.commit()
                main._send_telegram_message(chat_id, main._TG_CONTACT_RETRY_EXHAUSTED,
                                       reply_markup=main._REMOVE_KEYBOARD)
                main._audit("telegram_contact_exhausted", chat_id=chat_id_str)
                return {"ok": True}
            else:
                # Non-phone, non-escape — increment counter, re-show keyboard.
                with main.get_db_conn() as conn:
                    main._db_set_session_state(conn, session_id,
                                          main._make_contact_state(retry + 1))
                    conn.commit()
                main._send_contact_keyboard(chat_id, main._TG_AWAITING_CONTACT_RETRY)
                return {"ok": True}

        # ── 5. Content guards (only reached when not in a state machine branch) ─
        # Generous cap: this audience sends long, heartfelt messages. The funnel
        # states (handled above) have NO length limit at all; this only bounds
        # free-form RAG chat to keep the LLM token cost sane while still letting a
        # full emotional paragraph through (Telegram's own hard limit is 4096).
        if len(text) > 1500:
            main._send_telegram_message(chat_id, main._TG_TOO_LONG)
            return {"ok": True}
        try:
            main.validate_question(text)
        except main.InputModerationError:
            main._audit("telegram_moderation_block", chat_id=chat_id_str)
            main._send_telegram_message(chat_id, main._TG_MODERATION)
            return {"ok": True}

        # (awaiting_qualification is handled earlier — before the escape gate and
        # moderation — so a raw emotional story is captured, never rejected.)

        # ── Regex phone fallback for normal conversation ───────────────────────
        phone_in_text = main._extract_phone_from_text(text)
        if phone_in_text and not already_lead:
            try:
                intent_summary = main._build_intent_summary(history, text)
                with main.get_db_conn() as conn:
                    lead_id = main._db_save_lead(conn, session_id, chat_id_str,
                                            None, phone_in_text, intent_summary)
                    conn.commit()
                if lead_id:
                    # Confirm first (instant ack), then sync (P1).
                    main._send_telegram_message(chat_id, main._format_lead_thanks(None))
                    main._finalize_lead(lead_id, None, phone_in_text, intent_summary, chat_id_str)
                    main._audit("lead_captured_regex", chat_id=chat_id_str, lead_id=lead_id)
                    return {"ok": True}
            except Exception as e:
                main.logger.error(f"[leads] Regex capture failed: {e}", exc_info=True)

        # ── SAFETY NET: agreement to an offer whose state was lost ─────────────
        # Normally an offer arms 'offered_meeting', so the agreement turn is
        # handled above. But the state can be lost — most commonly when the 24h
        # bot_state TTL expires before the user replies. If we are NOT in a funnel
        # state yet the user clearly affirms AND our last message was an offer,
        # honour it and open the contact keyboard. This makes "אשמח" foolproof
        # regardless of how (or how long after) the conversation flowed.
        if (bot_state is None and not already_lead
                and main._is_affirmation(text) and main._last_bot_message_offered(history)):
            with main.get_db_conn() as conn:
                main._db_save_message(conn, session_id, "user", text)
                main._db_set_session_state(conn, session_id, main._make_contact_state(0))
                main._db_touch_session(conn, session_id)
                conn.commit()
            main._send_contact_keyboard(chat_id, main._TG_OFFER_ACK)
            main._audit("telegram_offer_accepted_recovered", chat_id=chat_id_str,
                   session_id=session_id)
            # NEXUS C3 (state-loss recovery path) — best-effort, never raises.
            main.nexus_hooks.on_funnel_event(
                "qualified", "telegram", session_id=session_id,
                stage="qualified", dedup_key=f"qualified:{session_id}")
            return {"ok": True}

        # ── BOOKING INTENT: deterministic funnel entry (no RAG) ───────────────
        # A scheduling request is owned by the STATE MACHINE, not the LLM.
        # Previously PATH B ran RAG and THEN appended the scripted question, so
        # the persona-driven LLM produced its own closing ("the team will get
        # back to you") that contradicted the follow-up question — the
        # double-message bug. We now answer with a single deterministic message
        # and skip the embed+LLM round-trip entirely:
        #   • existing lead → short on-brand ack (we already have their details).
        #   • new lead      → the qualification question; advance to
        #                     awaiting_qualification so their NEXT reply opens the
        #                     contact keyboard (handled by PATH A above).
        if bot_state is None and main._has_booking_intent(text):
            if already_lead:
                reply_text  = main._TG_ALREADY_LEAD_BOOKING
                new_state   = None
                audit_event = "telegram_already_lead_booking"
            else:
                reply_text  = main._TG_QUALIFICATION_QUESTION
                new_state   = "awaiting_qualification"
                audit_event = "telegram_qualification_triggered"

            with main.get_db_conn() as conn:
                main._db_save_message(conn, session_id, "user", text)
                main._db_save_message(conn, session_id, "assistant", reply_text)
                if new_state:
                    main._db_set_session_state(conn, session_id, new_state)
                main._db_touch_session(conn, session_id)
                conn.commit()

            main._send_telegram_message(chat_id, reply_text)
            main._audit(audit_event, chat_id=chat_id_str, session_id=session_id)
            # NEXUS C4 — funnel entry on Telegram. Opens (or re-opens after a
            # closed episode) the opportunity at 'engaged'. Best-effort.
            main.nexus_hooks.on_funnel_event(
                "trigger_hit", "telegram", session_id=session_id,
                stage="engaged",
                payload={"trigger": "booking_intent",
                         "already_lead": already_lead})
            return {"ok": True}

        # ── PATH B: triage receptionist (LLM proposes, state machine disposes) ─
        # The LLM returns {reply, intent}: it VALIDATES briefly and CLASSIFIES
        # whether to connect the user to Erez — it never writes the call-to-action
        # or transitions the funnel. Code owns the CTA + state change, so a funnel
        # closure can't be hallucinated and the persona can't drift into therapy.
        query_vector = main._embed_text(text)
        recall_block = ""
        with main.get_db_conn() as conn:
            chunks = main._retrieve_chunks(conn, query_vector, top_k=5)
            # NEXUS Hook F — memory recall (3.5 Phase 2). Gated by the live
            # memory.recall_enabled flag; build_recall_block is read-only and
            # returns "" on any failure, so the prompt is unchanged when off,
            # for unknown persons, or on a recall hiccup.
            if main._memory_recall_on():
                recall_block = main.nexus_memory.build_recall_block(
                    conn, session_id=session_id)

        reply, intent, sources = main._bot_triage_reply(text, chunks, history=history,
                                                   recall_block=recall_block)

        # Offer is the default for anything SUBSTANTIVE (EMOTIONAL or FAQ) — only
        # SMALLTALK stays out of the funnel — and only for a NEW lead (an existing
        # lead just gets the brief reply; Erez already has their details).
        make_offer = (intent in ("EMOTIONAL", "FAQ") and not already_lead)
        out = f"{reply}\n\n{main._TG_MEETING_CTA}" if make_offer else reply

        with main.get_db_conn() as conn:
            main._db_save_message(conn, session_id, "user", text)
            main._db_save_message(conn, session_id, "assistant", out)
            if make_offer:
                main._db_set_session_state(conn, session_id, main._make_offer_state(0))
            main._db_touch_session(conn, session_id)
            conn.commit()

        main._audit("telegram_triage", chat_id=chat_id_str, session_id=session_id,
               intent=intent, offered=make_offer, sources=sources, chunks=len(chunks))

        main._send_telegram_message(chat_id, out)

    except TimeoutError:
        main.logger.error("[telegram] LLM timeout")
        main._send_telegram_message(chat_id, main._TG_TIMEOUT)
    except Exception as e:
        main.logger.error(f"[telegram] Unexpected {type(e).__name__}: {e}", exc_info=True)
        main._send_telegram_message(chat_id, main._TG_ERROR)

    return {"ok": True}


@router.get("/api/webhook/instagram")
def instagram_webhook_verify(
    hub_mode:         str = None,
    hub_verify_token: str = None,
    hub_challenge:    str = None,
):
    """
    Meta webhook verification handshake (GET).
    Meta sends ?hub.mode=subscribe&hub.verify_token=<your_token>&hub.challenge=<int>.
    We must echo the challenge integer as plain text with HTTP 200.
    """
    if hub_mode == "subscribe" and main._secret_eq(hub_verify_token, main.settings.ig_verify_token):
        main.logger.info("[instagram] Webhook verified by Meta.")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=hub_challenge or "")
    main.logger.warning("[instagram] Webhook verification failed — bad verify_token.")
    raise main.HTTPException(status_code=403, detail="Verification failed.")


@router.post("/api/webhook/instagram")
async def instagram_webhook(
    request: main.Request,
    x_hub_signature_256: main.Optional[str] = main.Header(default=None),
):
    """
    Instagram DM webhook — POST handler for incoming messages.

    async by design: we must read the RAW request body (await request.body())
    to verify Meta's HMAC against the exact bytes it signed. The heavy, blocking
    processing (DB / embedding / LLM / urllib) is then offloaded to a worker
    thread via run_in_threadpool so it never stalls the event loop.

    Security:
      • X-Hub-Signature-256: HMAC-SHA256 of the RAW body with IG_APP_SECRET.
        Verified when IG_APP_SECRET is set; skipped in local dev (fail-open,
        same pattern as the Telegram webhook).
      • is_echo filter: Meta echoes our own sends back — we drop them.
      • DM-only filter: non-text payloads (stickers, voice, story-replies) ignored.
      • mid dedup: Meta may redeliver; processed message-ids tracked for 5 min.

    Always returns 200 {"ok": true} — never surfaces a 4xx/5xx or Meta retries
    and the user gets duplicate messages.
    """
    raw = await request.body()

    # ── 1. Signature verification (against the RAW bytes Meta signed) ──────────
    if main.settings.ig_app_secret:
        if not main._ig_verify_signature(raw, x_hub_signature_256):
            main.logger.warning("[instagram] Rejected: bad X-Hub-Signature-256.")
            return {"ok": True}   # 200 but do nothing — never 4xx to Meta

    # ── 2. Parse JSON and offload processing to a worker thread ────────────────
    try:
        body = main.json.loads(raw or b"{}")
    except Exception:
        main.logger.warning("[instagram] Could not parse webhook body as JSON.")
        return {"ok": True}

    await main.run_in_threadpool(main._process_instagram_events, body)
    return {"ok": True}


@router.get("/api/webhook/whatsapp")
def whatsapp_webhook_verify(request: main.Request):
    """
    Meta webhook verification handshake (GET), one-time at subscription.
    Meta sends ?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<int>.
    Read straight from query_params — the dotted keys ('hub.mode') do not bind to
    Python parameter names, so this is the robust way to read them. Echo the
    challenge as plain text on success.
    """
    qp = request.query_params
    if (qp.get("hub.mode") == "subscribe"
            and main._secret_eq(qp.get("hub.verify_token"), main.settings.whatsapp_verify_token)):
        main.logger.info("[whatsapp] Webhook verified by Meta.")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=qp.get("hub.challenge") or "")
    main.logger.warning("[whatsapp] Webhook verification failed — bad verify_token.")
    raise main.HTTPException(status_code=403, detail="Verification failed.")


@router.post("/api/webhook/whatsapp")
async def whatsapp_webhook(
    request: main.Request,
    x_hub_signature_256: main.Optional[str] = main.Header(default=None),
):
    """
    WhatsApp Cloud API webhook — POST handler. async so we can hash the RAW body
    (await request.body()) against Meta's HMAC before parsing. Blocking work is
    offloaded to a worker thread. Always returns 200 so Meta never retries into a
    duplicate-message storm. Mirrors the Instagram webhook exactly.
    """
    raw = await request.body()

    if main.settings.whatsapp_app_secret:
        if not main._wa_verify_signature(raw, x_hub_signature_256):
            main.logger.warning("[whatsapp] Rejected: bad X-Hub-Signature-256.")
            return {"ok": True}   # 200 but do nothing — never 4xx to Meta

    try:
        body = main.json.loads(raw or b"{}")
    except Exception:
        main.logger.warning("[whatsapp] Could not parse webhook body as JSON.")
        return {"ok": True}

    await main.run_in_threadpool(main._process_whatsapp_events, body)
    return {"ok": True}


@router.post("/api/webhooks/kapso")
async def kapso_webhook(
    request: main.Request,
    x_webhook_signature: main.Optional[str] = main.Header(default=None),
    x_webhook_event:     main.Optional[str] = main.Header(default=None),
    x_idempotency_key:   main.Optional[str] = main.Header(default=None),
):
    """Kapso inbound webhook. async so we can HMAC the RAW body before parsing.
    Verifies X-Webhook-Signature, then offloads to a worker and returns 200 fast
    (Kapso marks a delivery failed after 10s) so it never retries into a duplicate
    storm. Mirrors the Meta/Calendly webhook contract."""
    raw = await request.body()

    if main.settings.kapso_webhook_secret:
        if not main._kapso_verify_signature(raw, x_webhook_signature):
            main.logger.warning("[kapso] Rejected: bad X-Webhook-Signature.")
            return {"ok": True}

    try:
        body = main.json.loads(raw or b"{}")
    except Exception:
        main.logger.warning("[kapso] Could not parse webhook body as JSON.")
        return {"ok": True}

    await main.run_in_threadpool(main._process_kapso_event,
                            x_webhook_event or "", x_idempotency_key, body)
    return {"ok": True}


@router.post("/api/webhooks/calendly")
async def calendly_webhook(
    request: main.Request,
    calendly_webhook_signature: main.Optional[str] = main.Header(default=None),
):
    """
    Calendly booking webhook (invitee.created / invitee.canceled).

    Security: verify the signed payload against CALENDLY_WEBHOOK_SIGNING_KEY over
    the RAW body before any processing. When the key is unset: inert in local dev
    (no VERCEL), fail-closed in production (drop unsigned). Always returns 200 so
    Calendly never retry-storms; the heavy work runs in a worker thread. The
    subscription is registered manually in Calendly's UI (operator-owned).
    """
    raw = await request.body()

    if main.settings.calendly_webhook_signing_key:
        if not main.nexus_bookings.verify_signature(
                raw, calendly_webhook_signature,
                main.settings.calendly_webhook_signing_key):
            main.logger.warning("[calendly] rejected webhook: bad/missing signature.")
            return {"ok": True}
    elif main.os.environ.get("VERCEL"):
        main.logger.error("[calendly] SIGNING_KEY not set — webhook disabled in production.")
        return {"ok": True}

    try:
        body = main.json.loads(raw or b"{}")
    except Exception:
        main.logger.warning("[calendly] could not parse webhook body as JSON.")
        return {"ok": True}

    await main.run_in_threadpool(
        main.nexus_bookings.process_event, body,
        on_confirmed=main._wa_send_booking_confirmation)
    return {"ok": True}
