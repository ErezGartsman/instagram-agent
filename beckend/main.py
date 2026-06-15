"""
DataLens Backend — NL2SQL Analytics Engine
FastAPI + PostgreSQL (Supabase) + Gemini

Production-ready with: lazy psycopg2 connection pool, LRU cache,
per-IP rate limiting, content moderation, LLM timeout guard,
structured audit logging, conversation history, and CSV export support.
"""

import logging
import os
import re
import time
import json
import hashlib
import hmac
import threading
import decimal
import datetime
import uuid
import urllib.request
import urllib.error
import concurrent.futures
from collections import OrderedDict
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

import psycopg2
import psycopg2.pool
from google import genai
from google.genai import types as genai_types
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from nexus import bookings as nexus_bookings
from nexus import db as nexus_db
from nexus import erasure as nexus_erasure
from nexus import hooks as nexus_hooks
from nexus import memory as nexus_memory


# ─── Config ───────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    gemini_api_key:      str
    supabase_db_url:     str   # Pooler URL — session mode (port 5432) for BI tools / persistent connections
    max_result_rows:     int = 500
    allowed_origins:     str = "http://localhost:5173"
    llm_timeout_seconds: int = 30       # hard deadline for Gemini calls
    rate_limit_requests: int = 10       # max requests per IP per window
    rate_limit_window:   int = 60       # sliding window in seconds
    cache_max_size:      int = 100      # max LRU cache entries
    # Bearer token for API auth. Empty string = auth disabled (local dev only).
    # Set a strong random value in production: openssl rand -hex 32
    nexus_api_key:       str = ""

    # ── Telegram bot (optional — webhook is inert until both are set) ──────────
    # telegram_bot_token:      from BotFather (/newbot), e.g. "123456789:AA…".
    # telegram_webhook_secret: a value YOU generate (openssl rand -hex 32) and
    #   pass to Telegram via setWebhook?secret_token=…; Telegram echoes it back
    #   in the X-Telegram-Bot-Api-Secret-Token header so we can reject spoofers.
    telegram_bot_token:      str = ""
    telegram_webhook_secret: str = ""
    # Your personal Telegram chat_id — get it from @userinfobot.
    # When set, the bot DMs you every time a new lead is captured.
    telegram_owner_chat_id:  str = ""

    # ── CRM lead sync (optional — inert until a provider is configured) ────────
    # The sync destination is a swappable adapter selected by crm_provider:
    #   "hubspot" → push to HubSpot (needs hubspot_private_token).
    #   "fake"    → in-memory no-op provider for local dev / tests (no network).
    #   ""        → disabled; lead capture behaves exactly as before.
    crm_provider:        str = "hubspot"
    # HubSpot Free — a Private App access token (Settings → Integrations →
    # Private Apps) with contacts + deals read/write scopes. Looks like pat-….
    hubspot_private_token: str = ""
    # Optional: pin the Deal pipeline + stage. Leave empty to auto-discover the
    # default pipeline's first stage on first use (cached for the process).
    hubspot_pipeline_id: str = ""
    hubspot_stage_id:    str = ""
    # Optional: internal name of a custom Contact property to receive the intent
    # summary. When empty the summary is attached as a Note on the contact.
    hubspot_intent_property: str = ""
    # Shared secret guarding the /api/cron/crm-sync reconciliation endpoint.
    cron_secret:         str = ""

    # ── Calendly booking webhook (the North Star: booked consultation) ──────────
    # Signing key for verifying the Calendly-Webhook-Signature header. Set in the
    # backend env; the webhook subscription is registered manually in Calendly's
    # UI. When empty, the webhook is inert in dev and fail-closed on Vercel.
    calendly_webhook_signing_key: str = ""

    # ── Instagram / Meta (optional — webhook is inert until ig_access_token is set) ─
    # ig_access_token:  Page access token from Meta developer dashboard.
    # ig_verify_token:  A value YOU choose; Meta sends it back during webhook
    #                   verification so you can confirm the GET came from Meta.
    # ig_app_secret:    App secret from Meta dashboard — used to verify
    #                   X-Hub-Signature-256 on incoming webhook POSTs.
    ig_access_token:  str = ""
    ig_verify_token:  str = ""
    ig_app_secret:    str = ""

    # ── WhatsApp Business Cloud API (Sprint 4 — the qualification funnel) ───────
    # All four are set in Vercel; the webhook is inert until they are present.
    # whatsapp_phone_number_id: the number's ID (WhatsApp → API Setup).
    # whatsapp_access_token:    System-User permanent token (whatsapp_business_
    #                           messaging + whatsapp_business_management scopes).
    # whatsapp_app_secret:      App → Settings → Basic — verifies X-Hub-Signature-256.
    # whatsapp_verify_token:    A value YOU choose; echoed back on the GET verify.
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token:    str = ""
    whatsapp_app_secret:      str = ""
    whatsapp_verify_token:    str = ""

    # ── Contact-capture CTAs for Instagram (env-var driven, never hardcoded) ────
    # whatsapp_number:  E.164 format without '+', e.g. "972501234567".
    #                   When set, a WhatsApp wa.me link button is shown as the
    #                   sole contact CTA in the awaiting_contact step on Instagram.
    #                   If absent, the bot falls back to asking the user to type
    #                   their phone number — the funnel stays operational with no
    #                   env-var changes needed for local dev.
    whatsapp_number:  str = ""

    # ── Instagram Icebreakers (strict deterministic trigger) ────────────────────
    # ig_icebreakers: a '|'-separated list of the EXACT Icebreaker texts you set
    #   up in the Meta dashboard, e.g.:
    #       IG_ICEBREAKERS=אשמח לפרטים על ייעוץ|איך קובעים פגישה?
    #   A cold DM engages the bot ONLY if its text exactly matches one of these
    #   (after trimming). Everything else is dropped in silence. No LLM is used
    #   on the cold path — this is the authenticity guarantee for a personal
    #   account. When empty, the bot only ever continues active funnel turns.
    ig_icebreakers:   str = ""

    # ig_trigger_words: a '|'-separated list of trigger phrases for EXISTING
    #   followers (who never see the native Icebreaker button, which only shows
    #   on brand-new threads). A direct DM that CONTAINS any of these (case-
    #   insensitive substring) enters the same funnel, e.g.:
    #       IG_TRIGGER_WORDS=ייעוץ|רוצה לקבוע|אשמח לפרטים
    #   Substring (not exact) so Hebrew prefixes match ("ייעוץ" → "לייעוץ").
    #   Still ZERO-LLM and deterministic; story replies are hard-dropped before
    #   this ever runs, so it can never fire on a vulnerable story share.
    ig_trigger_words: str = ""

    # ── Power BI embed (served to authenticated users only) ─────────────────────
    # The Azure tenant id + report id must NOT live in the public JS bundle (they
    # enable AD-tenant enumeration). They are served from /api/powerbi/config
    # behind require_auth instead. Set both in the backend env to enable the
    # Analytics view; leave empty to disable it gracefully.
    powerbi_report_id: str = ""
    powerbi_tenant_id: str = ""

    model_config = {"env_file": ".env"}

settings = Settings()


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _secret_eq(provided: Optional[str], expected: str) -> bool:
    """
    Constant-time secret comparison. Uses hmac.compare_digest so the time taken
    does not depend on how many leading characters match — closing a (small)
    timing side-channel on bearer tokens / shared secrets.
    """
    if not expected:
        return False
    return hmac.compare_digest((provided or ""), expected)


_bearer_scheme = HTTPBearer(auto_error=False)

def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> None:
    """
    Bearer token guard applied to all data endpoints (not /health or /db-test).

    Behaviour:
      • NEXUS_API_KEY not set / empty → auth is disabled; all requests pass through.
        This keeps local development friction-free without code changes.
      • NEXUS_API_KEY set → every request must carry:
            Authorization: Bearer <your-key>
        Any missing or wrong token gets a 401.

    Generate a production key:  openssl rand -hex 32
    """
    if not settings.nexus_api_key:
        return  # dev mode — auth disabled
    if credentials is None or not _secret_eq(credentials.credentials, settings.nexus_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("datalens")

# ── Audit logger ──────────────────────────────────────────────────────────────
# On Vercel (and any other read-only serverless environment) we cannot write
# to the local filesystem — the deployment directory is immutable and even
# relative paths like "audit.log" hit a PermissionError at import time,
# crashing the entire function before a single request is served.
#
# Detection: Vercel automatically sets the VERCEL=1 env var in every
# function environment.  When present we route audit events to stdout
# (prefixed [AUDIT]) so they appear in Vercel's Runtime Logs and remain
# searchable without any extra infrastructure.
#
# Locally: events go to audit.log as before, keeping the file-based audit
# trail for development and self-hosted deployments.
_audit_logger = logging.getLogger("datalens.audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

if os.environ.get("VERCEL"):
    # Serverless: write JSON audit lines to stdout — Vercel captures all stdout
    _audit_handler: logging.Handler = logging.StreamHandler()
    _audit_handler.setFormatter(logging.Formatter("[AUDIT] %(message)s"))
else:
    # Local / persistent server: write to audit.log
    _audit_handler = logging.FileHandler("audit.log", encoding="utf-8")
    _audit_handler.setFormatter(logging.Formatter("%(message)s"))

_audit_logger.addHandler(_audit_handler)

def _audit(event: str, **kwargs) -> None:
    """Write one structured JSON record to audit.log."""
    _audit_logger.info(json.dumps(
        {"ts": time.time(), "event": event, **kwargs},
        ensure_ascii=False, default=str,
    ))


# ── Persisted conversion telemetry (bot_events) ───────────────────────────────
# _audit() goes to a logfile that is ephemeral on serverless, so it can't power
# conversion metrics over time. _track() persists the funnel hinges to the
# bot_events table instead. Deliberately narrow: only the two events needed for
# the icebreaker→capture conversion rate, so the table stays lean and the
# authenticity-critical silent path is never burdened with a DB write.
_TRACKED_EVENTS = {"icebreaker_hit", "lead_captured", "context_provided"}


def _track(event: str, channel: str, session_id: Optional[str] = None, **meta) -> None:
    """
    Best-effort telemetry write to bot_events. NEVER raises and NEVER blocks the
    bot — a telemetry failure (or a missing table) is logged and swallowed.
    Only events in _TRACKED_EVENTS are persisted; anything else is a no-op.
    """
    if event not in _TRACKED_EVENTS:
        return
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO bot_events (channel, event, session_id, meta) "
                    "VALUES (%s, %s, %s, %s::jsonb)",
                    (channel, event, session_id,
                     json.dumps(meta, ensure_ascii=False, default=str)),
                )
            conn.commit()
    except Exception as e:
        logger.warning(f"[telemetry] track {event!r} failed: {e}")


def _redact_text(text: Optional[str]) -> str:
    """
    Privacy guard for logs/audit. User messages in this product are highly
    sensitive (relationships / dating coaching), so we never write raw message
    bodies to logs or the audit trail. Instead we record a non-reversible
    fingerprint — length + a short salted-ish hash — which is enough to correlate
    duplicate/abusive messages and debug flow without storing PII in cleartext.
    """
    s = text or ""
    digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]
    return f"<redacted len={len(s)} h={digest}>"


# ─── Database — lazy psycopg2 pool ────────────────────────────────────────────

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """
    Return the shared connection pool, initialising it on the very first call.

    WHY LAZY:
    Vercel serverless cold-starts are unreliable for lifespan startup hooks —
    if the DB call fails at import time it silently kills every subsequent
    request. By deferring to the first real request we also guarantee the
    pool is created with valid runtime env-vars and can surface a clean 503
    on error instead of a process crash.

    POOL SIZING:
    minconn=1  — keep one warm connection for low-traffic periods.
    maxconn=3  — Supabase free plan allows ~20 direct connections; 3 per
                 serverless instance leaves ample headroom for multiple
                 concurrent deployments.

    statement_timeout=35 000 ms — prevents a runaway query from blocking
    the pool longer than the LLM timeout window (30 s default).
    """
    global _pool
    if _pool is not None and not _pool.closed:
        return _pool
    with _pool_lock:
        # Double-checked locking: re-test after acquiring the lock in case
        # another thread raced us here and already initialised the pool.
        if _pool is None or _pool.closed:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=3,
                dsn=settings.supabase_db_url,
                connect_timeout=10,
                options="-c statement_timeout=35000",
            )
            logger.info("[db] Connection pool initialised (minconn=1, maxconn=3).")
    return _pool


@contextmanager
def get_db_conn():
    """
    Yield a connection from the pool and return it when the block exits.
    Any exception triggers a rollback before the connection is returned so
    it cannot re-enter the pool in a dirty transactional state.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── NEXUS wiring (Hook G) ─────────────────────────────────────────────────────
# Hand the pooled-connection factory to the nexus strangler package. nexus
# modules never import main (no circular import); best-effort hooks that need
# their own connection (e.g. the post-capture spine) obtain one through this
# bridge. See docs/NEXUS_V1_INTEGRATION_MAP.md for the full hook contract.
nexus_db.configure(get_db_conn)


# ─── Schema Cache ─────────────────────────────────────────────────────────────

_schema_cache: str = ""   # populated once on first chat request; never changes at runtime

# Tables that exist for infrastructure / identity management — never exposed to
# the LLM so it cannot generate SELECT queries against internal session data.
# Includes ALL NEXUS V1 spine/memory tables (pulled forward from ticket 3.7):
# nexus_reader has zero grants on them (data already blocked), but excluding
# them here also keeps their NAMES out of the LLM schema prompt and the
# /api/schema sidebar. The three memory tables (migration 003) are pre-listed
# so ticket 3.5 cannot forget to add them.
_INTERNAL_TABLES = {
    "sessions", "messages", "knowledge_base", "app_config", "leads",
    "tenants", "operators", "person", "person_identity", "merge_candidates",
    "interactions", "opportunities", "bookings",
    "person_profile", "session_summaries", "operator_notes", "erasure_log",
}

def get_schema_description(conn) -> str:
    """
    Return the public schema as a prompt-ready string.

    Queries information_schema so the description always reflects the live
    table structure without any manual synchronisation.  Result is cached
    after the first successful call so the round-trips don't run on every
    chat request.

    Internal tables (sessions, messages) are excluded so the LLM only sees
    the Instagram analytics tables it is allowed to query.
    """
    global _schema_cache
    if _schema_cache:
        return _schema_cache
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM   information_schema.tables
                WHERE  table_schema = 'public'
                  AND  table_type   = 'BASE TABLE'
                ORDER  BY table_name
            """)
            tables = [row[0] for row in cur.fetchall() if row[0] not in _INTERNAL_TABLES]

            lines = []
            for table in tables:
                cur.execute("""
                    SELECT column_name, data_type
                    FROM   information_schema.columns
                    WHERE  table_schema = 'public'
                      AND  table_name   = %s
                    ORDER  BY ordinal_position
                """, (table,))
                cols    = cur.fetchall()
                col_str = ", ".join(f"{c[0]} ({c[1]})" for c in cols)
                lines.append(f"Table '{table}': {col_str}")

        _schema_cache = "\n".join(lines)
        logger.info(f"[schema] Cache populated ({len(lines)} tables).")
        return _schema_cache
    except Exception as e:
        logger.error(f"[schema] Fetch failed: {e}")
        return ""


# ─── App Config — brand voice / persona (live-editable via Supabase) ──────────
# Keys live in the app_config table so they can be tuned in the Supabase
# dashboard WITHOUT a redeploy. Values are cached in-process with a short TTL.
# The hardcoded defaults below are the resilient fallback used when a row is
# missing, the DB is briefly unreachable, or there is no database at all
# (tests / CI) — so the bot never sounds broken.

_DEFAULT_CONFIG = {
    "persona.system": (
        "את/ה הקול הדיגיטלי של ארז גרצמן — מנטור לתודעה זוגית, ליחסים ולפסיכולוגיה "
        "של היכרויות (דייטינג). דבר/י תמיד בגוף ראשון, בחום אמיתי ובגובה העיניים, "
        "כאילו ארז עצמו משוחח. קדם/י את הרגש לפני העצה: קודם הקשבה ואמפתיה אמיתית, "
        "ורק אחר כך תובנה או כיוון מעשי. עברית טבעית, אישית וחמה — בלי טון תאגידי, "
        "רובוטי או מכירתי. כשעולה אתגר זוגי מורכב שמתאים לליווי של ארז, הציע/י "
        "בעדינות ובלי לחץ פגישת ייעוץ אישית כמרחב בטוח להעמיק בו — הצעה רכה, לא "
        "מכירה אגרסיבית. שמור/י על גבולות: אינך מטפל/ת או פסיכולוג/ית, ואינך תחליף "
        "לליווי מקצועי. אם אין מספיק מידע במאגר הידע, אמור/י זאת בכנות ובחום, "
        "והצע/י דרך אחרת לעזור."
    ),
    "telegram.greeting": (
        "היי, כמה טוב שכתבת 🤍 אני העוזר הדיגיטלי של ארז גרצמן — כאן כדי לדבר איתך "
        "על זוגיות, יחסים והיכרויות, בגובה העיניים. אפשר לשתף אותי במה שעובר עליך, "
        "לשאול על הליווי של ארז, או פשוט להתחיל לדבר. מה מביא אותך לכאן היום?"
    ),
    "crisis.message": (
        "אני שומע/ת אותך, ונשמע שאת/ה עובר/ת עכשיו תקופה ממש כואבת. את/ה לא לבד בזה, "
        "ומגיעה לך תמיכה אמיתית. אני רק עוזר דיגיטלי ולא תחליף לעזרה מקצועית — אז אם "
        'הכאב גדול, חשוב לי שתפנה/י לער"ן (עזרה ראשונה נפשית) בטלפון 1201. הקו פתוח '
        "בכל שעה, בחינם ובאנונימיות, ויש שם אנשים אמיתיים שאפשר לדבר איתם עכשיו. 🤍"
    ),
    # ── M4 consent surface (Ticket 3.6) — live-editable in Supabase ─────────────
    # disclosure.line: appended to the Telegram /start greeting (first contact).
    # consent.capture_line: appended at EVERY phone-collection moment (both
    # channels). Empty value => the line is silently omitted.
    "disclosure.line": (
        "אני העוזר הדיגיטלי של ארז 🤍 השיחה שלנו נשמרת כדי שארז יוכל לעבור עליה "
        "ולחזור אליך אישית."
    ),
    "consent.capture_line": (
        "הפרטים שלך נשמרים אך ורק כדי שנוכל לחזור אליך, ולא מועברים לאף אחד."
    ),
    # ── WhatsApp qualification flow (Ticket 4.2) ────────────────────────────────
    # These are the versioned BASELINE copy. To tune any line live (no redeploy),
    # add/edit the same key in the app_config table — it overrides the default
    # within the cache TTL. Only the insight is AI-generated; everything else is
    # fixed copy in Erez's voice. Gender-neutral by construction (no מ/נ slashes):
    # uses Hebrew's neutral object forms (לך/אותך/בא לך) + infinitives, so it
    # reads warm rather than like a form.
    "whatsapp.opening": (
        "היי ❤️\n"
        "אני כאן.\n"
        "בא לי לשמוע בכמה מילים מה עובר עליך עכשיו, ומה גרם לך לפנות דווקא ברגע הזה."
    ),
    "whatsapp.bridge": (
        "זאת בדיוק הסיבה שאני לא אוהב לתת תשובות של שתי שורות במצבים כאלה. "
        "בדרך כלל צריך להבין מה באמת מחזיק אותך שם. אם בא לך, אפשר לעשות שיחה "
        "אישית ולצלול לזה יותר לעומק."
    ),
    "whatsapp.price_offer": (
        "מעולה 🙏\n"
        "אני חושב ששיחה יכולה מאוד לעזור לעשות סדר במה שעובר עליך ולתת לך "
        "כיוון ברור להמשך.\n"
        "השיחה היא אישית, אחד על אחד, נמשכת כשעה והעלות שלה היא 250₪.\n"
        "אם זה מרגיש לך נכון, נבדוק יחד מועד שמתאים לך ❤️"
    ),
    "whatsapp.booking_leadin": (
        "מקסים 🙏 הנה הקישור לתיאום השיחה — אפשר לבחור את המועד שהכי נוח לך:"
    ),
    "whatsapp.decline": (
        "לגמרי בסדר, בלי שום לחץ 😊 ואם בא לך לחזור לזה בעתיד — אני כאן."
    ),
    "whatsapp.price_nudge": (
        "אין שום לחץ 🤍 אם בא לך, נמצא יחד מועד שמתאים לך — או שפשוט נמשיך "
        "לדבר על מה שעולה לך."
    ),
    "whatsapp.insight_fallback": (
        "נשמע שיש כאן משהו אמיתי, ושיש בו הרבה יותר ממה שאפשר לסכם בשתי שורות."
    ),
    # The anti-cringe instructions. Second-person reflection (never first-person),
    # down-to-earth everyday Hebrew, few-shot anchored. The story is appended in
    # code (see _wa_generate_insight).
    "whatsapp.insight_instructions": (
        "האדם שיתף איתך מה עובר עליו. המשימה שלך: לשקף לו בחזרה, במשפט אחד עד "
        "שניים בלבד, את הקונפליקט הפנימי שעולה מהמילים שלו.\n\n"
        "חוקי ברזל:\n"
        "- דבר אֵל האדם בגוף שני ('נראה שקשה לך…', 'נשמע שאתה תקוע…'). אסור "
        "בתכלית לדבר במקומו או בגוף ראשון ('אני מרגיש…', 'אני מתקשה…') — זאת לא "
        "ההרגשה שלך אלא שלו.\n"
        "- טון עממי, יומיומי וישיר, בגובה העיניים — כמו שחבר חכם היה מגיב. "
        "אמפתיה חדה ומדויקת.\n"
        "- בלי דרמה, בלי פיוט, בלי מליצות ובלי קלישאות (למשל 'החלום והתקווה', "
        "'המסע שלך'). משפט קצר שאדם אמיתי באמת אומר.\n"
        "- בלי פתרונות, בלי עצות, בלי הבטחות. אל תזכיר שיחה, פגישה או מחיר.\n"
        "- התאם את לשון הפנייה (זכר/נקבה) למי שכתב לך, לפי הניסוח שלו.\n"
        "- אסור להשתמש בביטויים גנריים כמו 'אני מבין בדיוק מה אתה עובר', "
        "'אל תדאג יש לי פתרון' או 'הרבה אנשים במצב שלך'.\n\n"
        "בחר ציר אחד בלבד, המדויק ביותר למה שכתב:\n"
        "(1) שכל מול רגש — בשכל הוא כבר יודע מה נכון, אבל הרגש עוד לא שם.\n"
        "(2) תשישות ולופ — מה שהכי מתיש זה להיות תקוע באותו לופ ולא להצליח לצאת.\n"
        "(3) מציאות מול פנטזיה — מצד אחד המציאות ברורה, מצד שני קשה לשחרר את "
        "מה שקיווה שיקרה.\n\n"
        "דוגמאות למבנה ולטון (אל תעתיק — תייצר משפט חדש לפי מה שהאדם כתב):\n"
        "• 'נראה שאתה מבין בשכל מה נכון, אבל הרגש עדיין לא שם.'\n"
        "• 'נשמע שהדבר שהכי מתיש אותך זה שאתה בלופ ולא מצליח לצאת ממנו.'\n"
        "• 'מצד אחד המציאות מולך ברורה, מצד שני קשה לשחרר את מה שקיווית שיהיה.'"
    ),
    # Calendly booking link: user-specific, so it lives in app_config (not the
    # repo). Empty default => the lead-in is sent without a link.
    "calendly.url": "",
}

_CONFIG_TTL      = 300        # seconds — edits in Supabase take effect within this window
_config_cache:   dict = {}    # key → value, loaded in bulk
_config_cache_ts: float = 0.0
_config_lock     = threading.Lock()

def _get_config(key: str) -> str:
    """
    Return an app_config value, preferring the DB (bulk-cached, TTL) over the
    hardcoded default. Never raises: any DB failure falls back to the default so
    a brief outage can't break the bot's voice or the /start greeting.
    """
    global _config_cache, _config_cache_ts
    now = time.time()
    with _config_lock:
        if now - _config_cache_ts > _CONFIG_TTL:
            try:
                with get_db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT key, value FROM app_config")
                        _config_cache = {k: v for k, v in cur.fetchall()}
            except Exception as e:
                logger.warning(f"[config] load failed: {e} — using defaults.")
                # keep whatever we had (possibly empty → defaults below)
            _config_cache_ts = now   # back off either way; no per-call retry storm
        value = _config_cache.get(key)
    return value if value else _DEFAULT_CONFIG.get(key, "")


def _config_suffix(key: str) -> str:
    """Return '\\n\\n<value>' for a config line, or '' when it's unset — so the
    M4 disclosure/consent lines can be appended anywhere and tuned (or removed)
    live in Supabase without a redeploy."""
    line = _get_config(key).strip()
    return f"\n\n{line}" if line else ""


# ─── Session & Message Persistence ───────────────────────────────────────────
# All four helpers are intentionally commit-free — the calling route handler
# owns the transaction boundary and calls conn.commit() at the right moment.
# This keeps reads and writes inside a single connection checkout, which is
# important given our pool size of 3.

def _db_create_session(conn, channel: str = "web", contact_id: str = None) -> str:
    """INSERT a new session row and return its UUID as a plain string."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (channel, contact_id)
            VALUES (%s, %s)
            RETURNING id, created_at
            """,
            (channel, contact_id),
        )
        row = cur.fetchone()
    return str(row[0]), str(row[1])   # (session_id, created_at)


def _db_load_history(conn, session_id: str, limit: int = 20) -> list:
    """
    Return the last `limit` messages for a session, ordered oldest → newest.
    Used to rebuild the LLM history context from the database so follow-up
    questions work correctly even after a page refresh.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, content, sql_used, row_count, created_at
            FROM   messages
            WHERE  session_id = %s
            ORDER  BY created_at DESC
            LIMIT  %s
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
    # Reverse: DESC fetch gives newest-first; we need oldest-first for the prompt.
    return [
        {
            "role":       r[0],
            "content":    r[1],
            "sql_used":   r[2],
            "row_count":  r[3],
            "created_at": str(r[4]),
        }
        for r in reversed(rows)
    ]


def _db_save_message(
    conn,
    session_id: str,
    role: str,
    content: str,
    sql_used: str = None,
    row_count: int = None,
) -> None:
    """INSERT one message turn. Caller must commit."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (session_id, role, content, sql_used, row_count)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, role, content, sql_used, row_count),
        )


def _db_touch_session(conn, session_id: str) -> None:
    """Bump last_active so the session appears first in recent-sessions queries."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET last_active = NOW() WHERE id = %s",
            (session_id,),
        )


# ─── Input Content Moderation ─────────────────────────────────────────────────
# Guard against clearly harmful or off-topic input before it reaches the LLM.
# Deliberately narrow — SQL keywords are handled downstream by validate_sql().

# Harm-only blocklist. This product is an emotional / relationships & dating
# coaching assistant, so its users legitimately use profanity, intimacy
# vocabulary, and raw negative language while venting ("he treats me like shit",
# "our sex life died", "he sent nudes to someone else"). Blocking those would
# reject genuine stories — the exact systemic failure this guard must avoid.
# We therefore block ONLY content the assistant must never engage with at all,
# regardless of empathy: hate slurs, CSAM, incitement to violence against
# others, terror/weapons, and cyber-harm. Acute self-harm / suicidality is NOT
# moderated here — it is handled compassionately and FIRST by is_crisis().
_BLOCKED_TERMS = re.compile(
    r"\b(nigger|faggot|kike|"                     # hate slurs
    r"child\s*por\w*|"                            # CSAM
    r"kill\s+(?:yourself|him|her|them)|"          # incitement to violence against others
    r"bomb(?:ing)?|terrorist|"                    # terror / weapons
    r"malware|ransomware)\b",                     # cyber-harm
    re.IGNORECASE,
)

class InputModerationError(Exception):
    pass

def validate_question(question: str) -> str:
    """Raise InputModerationError for clearly harmful content."""
    if len(question.strip()) < 3:
        raise InputModerationError("Question is too short.")
    if _BLOCKED_TERMS.search(question):
        raise InputModerationError("Input contains inappropriate content.")
    return question.strip()


# ── Crisis / distress detection ───────────────────────────────────────────────
# Distinct from moderation: for a relationships & coaching brand, a user
# expressing self-harm or acute distress must NOT get the cold "can't process
# this" block. The empathetic representative paths (Telegram + web "Ask Erez")
# check this FIRST and respond with the compassionate crisis.message
# (config-driven; points to ERAN / ער"ן 1201) instead of running the LLM.
_CRISIS_TERMS = re.compile(
    r"(אובדני|להתאבד|לשים\s*קץ|לסיים\s*את\s*הכל|רוצה\s*למות|"
    r"לא\s*רוצה\s*לחיות|אין\s*טעם\s*לחיות|אין\s*לי\s*סיבה\s*לחיות|"
    r"לפגוע\s*בעצמ|פגיעה\s*עצמית|"
    r"suicide|suicidal|kill\s*myself|end\s*my\s*life|want\s*to\s*die|"
    r"don'?t\s*want\s*to\s*live|self[\s_\-]*harm|hurt\s*myself|no\s*reason\s*to\s*live)",
    re.IGNORECASE,
)

def is_crisis(text: str) -> bool:
    """True if the message signals acute emotional distress / self-harm."""
    return bool(_CRISIS_TERMS.search(text or ""))


# ─── Per-IP Rate Limiter ──────────────────────────────────────────────────────

_rate_lock = threading.Lock()
_rate_store: dict[str, list[float]] = {}
_rate_req_count = 0

class RateLimitError(Exception):
    pass

def get_client_ip(request: Request) -> str:
    """
    Resolve the real client IP in order of trust:
      1. X-Forwarded-For (Nginx, Cloudflare, AWS ALB) — first entry is the client.
      2. X-Real-IP (Nginx single-proxy convention).
      3. Direct connection host (local dev / no proxy).
    Without this, behind any reverse proxy every user shares the proxy's IP
    and rate limiting is effectively disabled.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str) -> None:
    """
    Sliding-window rate limiter.
    Raises RateLimitError if ip has exceeded settings.rate_limit_requests
    in the last settings.rate_limit_window seconds.
    Every 100 requests, stale IP keys are evicted to prevent unbounded growth.

    KNOWN LIMITATION (serverless): _rate_store is in-process, so on Vercel each
    function instance keeps its own counter and a cold start resets it. This is a
    best-effort guard against accidental floods, NOT a hard cross-instance limit.
    For strict global rate limiting, back this with a shared store (e.g. Upstash
    Redis / a Supabase table). Acceptable at current volume; revisit if abused.
    """
    global _rate_req_count
    now = time.time()
    with _rate_lock:
        timestamps = _rate_store.get(ip, [])
        timestamps = [t for t in timestamps if now - t < settings.rate_limit_window]
        if len(timestamps) >= settings.rate_limit_requests:
            raise RateLimitError(f"IP {ip!r} exceeded rate limit")
        timestamps.append(now)
        _rate_store[ip] = timestamps
        _rate_req_count += 1
        if _rate_req_count % 100 == 0:
            cutoff = now - settings.rate_limit_window
            stale = [k for k, v in list(_rate_store.items()) if not v or v[-1] < cutoff]
            for k in stale:
                del _rate_store[k]


# ─── LRU Query Cache ──────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 3600  # 1 hour — stale results beyond this are re-queried

class _LRUCache:
    """Thread-safe LRU cache backed by OrderedDict with a per-entry TTL."""
    def __init__(self, maxsize: int, ttl: int = _CACHE_TTL_SECONDS):
        self._cache: OrderedDict[str, tuple[dict, float]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl     = ttl
        self._lock    = threading.Lock()

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            if key not in self._cache:
                return None
            value, ts = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                logger.info(f"[cache] EXPIRED {key[:60]!r}")
                return None
            self._cache.move_to_end(key)
            logger.info(f"[cache] HIT {key[:60]!r}")
            return value

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._maxsize:
                    self._cache.popitem(last=False)
            self._cache[key] = (value, time.time())

_query_cache = _LRUCache(maxsize=settings.cache_max_size)


# ─── SQL Validation ───────────────────────────────────────────────────────────

_ALLOWED_START_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_DANGEROUS_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        # DML / DDL — never permitted
        r"\bDROP\b", r"\bDELETE\b", r"\bINSERT\b",
        r"\bUPDATE\b", r"\bCREATE\b", r"\bALTER\b",
        r"\bTRUNCATE\b", r"\bEXEC\b", r"\bCOPY\b",
        # PostgreSQL server-side filesystem / OS access functions —
        # a prompt-injected query like SELECT pg_read_file('/etc/passwd')
        # passes the SELECT-start check but reads arbitrary server files.
        r"\bpg_read_file\b",
        r"\bpg_ls_dir\b",
        r"\bpg_sleep\b",
        r"\bpg_execute\b",
        r"\blo_export\b",
        r"\blo_import\b",
        # Session-state mutation (unnecessary for read-only analytics)
        r"\bSET\b",
    ]
]

class SQLValidationError(Exception):
    pass

def validate_sql(sql: str) -> str:
    """
    Strip trailing semicolons (Gemini occasionally appends one, which breaks
    psycopg2 when the SQL is later wrapped inside a subquery), then assert
    SELECT/WITH-only and the absence of dangerous keywords.
    WITH is allowed to support Common Table Expressions (CTEs).
    """
    sql = sql.strip().rstrip(";").rstrip()
    if not _ALLOWED_START_PATTERN.match(sql):
        raise SQLValidationError(f"Only SELECT/WITH queries permitted. Got: {sql[:60]!r}")
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(sql):
            raise SQLValidationError(f"Forbidden keyword: {pattern.pattern}")
    return sql


def _serialize_val(v) -> object:
    """Convert a psycopg2 result value to a JSON-serialisable Python type."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    return str(v)


def execute_query(conn, sql: str) -> tuple:
    """
    Wrap validated SQL in a LIMIT guard and execute via psycopg2.
    Returns (rows: list[tuple], columns: list[str]).

    DEFENSE-IN-DEPTH (read-only execution):
    validate_sql() is a blocklist + SELECT/WITH allowlist, but blocklists are
    inherently fragile. We additionally execute the untrusted/LLM-generated SQL
    inside a read-only SAVEPOINT: `SET LOCAL transaction_read_only = on` makes
    Postgres itself reject ANY write (INSERT/UPDATE/DELETE, data-modifying CTEs,
    etc.) at execution time, even if one slipped past the regex. ROLLBACK TO the
    savepoint then restores writability so the caller's legitimate writes
    (messages/leads) in the same transaction still succeed. The SELECT rows are
    already fetched into Python, so the rollback discards nothing we need.

    psycopg2 connections are thread-safe; no global lock is needed because
    each request gets its own connection from the pool.
    """
    safe_sql = f"SELECT * FROM ({sql}) AS _q LIMIT {settings.max_result_rows}"
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT _ro_guard")
        # Layer 1 — write-blocking: Postgres itself rejects any DML even if the
        # regex blocklist were bypassed (e.g. via string-concatenation tricks).
        cur.execute("SET LOCAL transaction_read_only = on")
        # Layer 2 — schema restriction: switch to the analytics-only reader role
        # so raw user SQL can only touch posts/comments/likers/followers and cannot
        # reach leads, messages, sessions, knowledge_base, or auth.* tables.
        # SET LOCAL ROLE is reverted by ROLLBACK TO SAVEPOINT, so app writes in
        # the same connection still run as the original (full-access) role.
        # Requires the nexus_reader role to exist — see sql/sprint1e_nexus_reader.sql.
        #
        # FAIL-CLOSED (Sprint 1E policy): if we cannot drop to nexus_reader we MUST
        # NOT fall back to running user SQL as the full-privilege role. A failed
        # statement aborts the sub-transaction, so we ROLLBACK TO / RELEASE the
        # savepoint to restore the connection to a clean state (leaving it usable
        # for the pool), then raise — the query is blocked entirely.
        try:
            cur.execute("SET LOCAL ROLE nexus_reader")
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT _ro_guard")
            cur.execute("RELEASE SAVEPOINT _ro_guard")
            logger.error("[db] could not assume nexus_reader role — BLOCKING raw query "
                         "(fail-closed). Run sql/sprint1e_nexus_reader.sql in Supabase. "
                         "err=%s", e)
            raise HTTPException(
                status_code=500,
                detail="Query blocked: schema-restriction role unavailable.",
            ) from e
        try:
            cur.execute(safe_sql)
            columns = [desc[0] for desc in cur.description]
            rows    = cur.fetchall()
        finally:
            # ROLLBACK TO restores both transaction_read_only AND the role to their
            # pre-savepoint values. RELEASE cleans up the savepoint record.
            cur.execute("ROLLBACK TO SAVEPOINT _ro_guard")
            cur.execute("RELEASE SAVEPOINT _ro_guard")
    return rows, columns


# ─── LLM Pipeline ─────────────────────────────────────────────────────────────

_gemini_client = genai.Client(api_key=settings.gemini_api_key)

# Module-level thread pool — avoids spawning a new pool on every request
_llm_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="gemini"
)

def _call_llm(prompt: str) -> str:
    """
    Submit the Gemini call to the thread pool with a hard timeout.
    Raises TimeoutError if Gemini doesn't respond within llm_timeout_seconds.
    Uses the new google-genai SDK (replaces deprecated google-generativeai).
    """
    def _generate():
        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()

    future = _llm_executor.submit(_generate)
    try:
        return future.result(timeout=settings.llm_timeout_seconds)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(
            f"Gemini did not respond within {settings.llm_timeout_seconds}s"
        )

def _parse_llm_json(raw_text: str) -> dict:
    """
    Multi-pass repair pipeline that tolerates the most common LLM JSON hallucinations:
      Pass 1 – strip markdown fences (any language tag, opening and closing)
      Pass 2 – isolate the outermost { … } object
      Pass 3 – remove trailing commas before } or ]
      Pass 4 – escape literal newline / carriage-return characters inside string values
      Pass 5 – re-escape bare double-quotes inside string values (char-level scanner)
    After each structural pass a fast json.loads() is tried so we bail out early
    if the text is already valid.
    """
    # ── Pass 1: strip markdown fences ─────────────────────────────────────────
    text = raw_text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    # ── Pass 2: isolate outermost JSON object ──────────────────────────────────
    first_brace = text.find('{')
    last_brace  = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Pass 3: remove trailing commas ────────────────────────────────────────
    text = re.sub(r",\s*(?=[}\]])", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Pass 4: escape literal newlines inside quoted string values ────────────
    def _escape_newlines_in_string(m: re.Match) -> str:
        s     = m.group(0)
        inner = s[1:-1]
        inner = inner.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')
        return '"' + inner + '"'

    text = re.sub(r'"(?:[^"\\]|\\.)*"', _escape_newlines_in_string, text, flags=re.DOTALL)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Pass 5: re-escape bare double-quotes inside string values ──────────────
    _AFTER_STRING = re.compile(r'\s*[:,}\]]')

    def _fix_bare_quotes(s: str) -> str:
        out = []
        i   = 0
        n   = len(s)
        while i < n:
            ch = s[i]
            if ch == '\\':
                out.append(ch)
                i += 1
                if i < n:
                    out.append(s[i])
                    i += 1
                continue
            if ch == '"':
                out.append('"')
                i += 1
                while i < n:
                    c = s[i]
                    if c == '\\':
                        out.append(c)
                        i += 1
                        if i < n:
                            out.append(s[i])
                            i += 1
                        continue
                    if c == '"':
                        rest = s[i + 1:]
                        if _AFTER_STRING.match(rest) or (i + 1 == n):
                            out.append('"')
                            i += 1
                            break
                        else:
                            out.append('\\"')
                            i += 1
                            continue
                    out.append(c)
                    i += 1
                continue
            out.append(ch)
            i += 1
        return ''.join(out)

    text = _fix_bare_quotes(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        snippet = raw_text[:200].replace('\n', '↵')
        raise ValueError(
            f"LLM returned unparseable JSON after all repair passes. "
            f"JSONDecodeError: {exc}. Raw (first 200 chars): {snippet}"
        ) from exc


COMBINED_PROMPT_TEMPLATE = """\
You are a smart bilingual data assistant. Your job is to decide whether the \
user's message requires a database query or is just general conversation, \
then respond appropriately.

Database schema:
{schema}

{history_block}=== DECISION RULES ===

CASE A — The user is asking for data or analysis from the database:
  → Return: {{"sql": "<valid PostgreSQL SELECT query>", "reply": "<short lead-in sentence>"}}

CASE B — The user is chatting, greeting, asking what you can do, or the \
message is gibberish / completely unrelated to the data:
  → Return: {{"sql": null, "reply": "<friendly conversational response>"}}

=== SQL RULES (applies only to CASE A) ===
- The database is PostgreSQL. Write standard ANSI SQL with PostgreSQL syntax.
- Use ONLY tables and columns that exist in the schema above.
- All timestamp columns (posted_at_ts, commented_at, followed_at) are TIMESTAMPTZ.
- For date range filtering: WHERE posted_at_ts > NOW() - INTERVAL '30 days'
- For date truncation: DATE_TRUNC('month', posted_at_ts)
- For year/month extraction: EXTRACT(year FROM posted_at_ts), EXTRACT(month FROM posted_at_ts)
- Do NOT use: try_strptime, epoch_ms, read_csv_auto, read_json_auto (these are DuckDB functions).
- Do NOT end the SQL with a semicolon.
- Only SELECT queries are allowed.

=== FOLLOWERS TABLE — JOIN RULES ===
The schema includes a table called `followers` with two columns:
  • username (VARCHAR) — the follower's Instagram handle
  • followed_at (TIMESTAMPTZ) — when they followed the account

To analyse overlap between followers and engagement data, JOIN on the `username` field:
  • followers ↔ likers:   JOIN followers f ON f.username = l.username   (likers alias: l)
  • followers ↔ comments: JOIN followers f ON f.username = c.username   (comments alias: c)

Example — followers who also liked a post:
  SELECT f.username, f.followed_at
  FROM followers f
  JOIN likers l ON l.username = f.username
  WHERE l.post_shortcode = '<shortcode>'

Example — followers who have never commented:
  SELECT f.username FROM followers f
  LEFT JOIN comments c ON c.username = f.username
  WHERE c.username IS NULL

=== LANGUAGE RULES — THIS IS MANDATORY, NEVER IGNORE ===
- The user communicates in Hebrew. ALL user-facing text in the "reply" field \
MUST be written in fluent, native Hebrew.
- *** Writing English in the "reply" field is a critical failure. ***
- Exception: you MAY keep specific technical terms in their original form — \
column names (e.g. username, likes, post_shortcode), Instagram-specific \
jargon, or exact numeric values — but the surrounding sentence must be Hebrew.
- For CASE A: DO NOT include actual data values or numbers in the "reply". \
Python appends the real results automatically.

=== TONE & STYLE RULES — STRICTLY ENFORCED ===
- Write at eye level: grounded, direct, and data-driven. Sound like a sharp \
analyst briefing a colleague, not a chatbot performing enthusiasm.
- Strictly forbidden: robotic filler ("בהחלט!", "כמובן!", "נהדר!"), \
hollow openers ("אשמח לעזור"), clichés, metaphors, or poetic flourishes.
- Keep replies short and concrete. One sentence is usually enough for a lead-in. \
State what the data shows — nothing more.

=== FORMAT RULES — STRICTLY ENFORCED ===
- Return ONLY a single valid JSON object. No markdown fences, no preamble, no trailing text.
- The only two valid shapes are:
    {{"sql": "<query>", "reply": "<lead-in>"}}
    {{"sql": null,      "reply": "<conversational response>"}}

*** JSON ENCODING RULES — EVERY RULE IS MANDATORY ***

1. NO MARKDOWN FENCES — never wrap the JSON in ```json ... ``` or any code block.

2. NO LITERAL NEWLINES INSIDE STRINGS — every string value must fit on a single line. \
   WRONG:  {{"reply": "שורה ראשונה\nשורה שנייה"}}   ← literal newline in the value \
   CORRECT:{{"reply": "שורה ראשונה. שורה שנייה."}}   ← single line, period-separated

3. NEVER USE DOUBLE QUOTES INSIDE THE SQL STRING — the "sql" JSON value is itself \
   delimited by double quotes. Any literal " inside it corrupts the JSON object. \
   This is why SQL column aliases MUST use the unquoted-underscore strategy \
   (see SQL ALIAS RULE below) — never double-quoted aliases. \
   WRONG:  {{"sql": "SELECT COUNT(*) AS "מספר עוקבים" FROM posts"}} \
   CORRECT:{{"sql": "SELECT COUNT(*) AS מספר_עוקבים FROM posts"}} \
   If any other literal " must appear inside the SQL string, escape it as \".

4. NO TRAILING COMMAS — trailing commas after the last key-value pair are illegal JSON. \
   WRONG:  {{"sql": null, "reply": "שלום",}} \
   CORRECT:{{"sql": null, "reply": "שלום"}}

5. DOUBLE-QUOTED KEYS AND VALUES ONLY — never use single quotes ('sql', 'reply'). \
   WRONG:  {{'sql': null, 'reply': 'שלום'}} \
   CORRECT:{{"sql": null, "reply": "שלום"}}

*** CRITICAL LANGUAGE-MIRRORING RULE — NO EXCEPTIONS ***
Detect the language of the user's question and write the "reply" value in that \
exact same language. The rule is absolute: \
  • User asks in Hebrew  → reply in Hebrew. \
  • User asks in English → reply in English. \
  • User asks in any other language → reply in that language. \
Do NOT default to Hebrew when the user wrote in English. \
The JSON keys ("sql", "reply") are always English — that is structural, not content. \

SQL ALIASES are exempt from language-mirroring: aliases are always Hebrew with \
underscores regardless of the question language (see SQL ALIAS RULE below). \
This is because aliases are internal SQL identifiers, not user-facing text. \

WRONG (user asked in English): {{"reply": "חמשת המשתמשים הפעילים ביותר הם…"}} \
CORRECT (user asked in English): {{"reply": "The top 5 most active users are…"}} \
CORRECT (user asked in Hebrew):  {{"reply": "חמשת המשתמשים הפעילים ביותר הם…"}}

*** CRITICAL SQL ALIAS RULE — NO SPACES, NO QUOTES, UNDERSCORES ONLY ***
SQL column aliases MUST be bare (unquoted) identifiers that contain NO spaces. \
Use a single underscore to join Hebrew words. This applies to every alias — \
Hebrew and English alike.

WHY NOT SINGLE QUOTES: PostgreSQL treats AS 'מספר תגובות' as a string literal, not \
a column identifier. That literal silently does nothing in ORDER BY, GROUP BY, and \
HAVING — the query runs but returns wrong or unsorted results. \
WHY NOT DOUBLE QUOTES: A double-quoted alias (AS "שם") embeds a literal " inside \
the JSON "sql" string value, corrupting the JSON and crashing the parser.

WRONG:  SELECT COUNT(*) AS 'מספר_עוקבים'   ← single-quoted = string literal \
WRONG:  SELECT COUNT(*) AS "מספר_עוקבים"   ← double-quoted = corrupts JSON \
WRONG:  SELECT COUNT(*) AS מספר עוקבים     ← space = SQL syntax error \
CORRECT:SELECT COUNT(*) AS מספר_עוקבים     ← bare identifier, underscore-joined \
CORRECT:SELECT COUNT(*) AS follower_count   ← English underscore alias also fine \

Apply this to every aliased or computed column (COUNT, SUM, AVG, expressions). \
Raw column references that need no alias (e.g. username, post_shortcode) are exempt.

*** KPI / NUMBER RULE — NO NAKED NUMBERS ***
Never place a bare number in the "reply" field without a Hebrew label beside it. \
WRONG reply: "1263 | 2427" \
CORRECT reply: "מתוך 2,427 עוקבים — 1,263 הגיבו לפחות פעם אחת." \
Always add the unit or entity name next to every figure.

*** TONE OVERRIDE — MANDATORY ***
Speak like a brilliant but down-to-earth colleague. Be concise and direct. \
Use everyday Hebrew — בגובה העיניים. \
Never open with "הנה", "להלן", "בהחלט", "זהו פילוח", or any descriptive preamble. \
Skip straight to the insight. One sharp sentence beats three bland ones.

User message: "{question}"
"""

_EMPTY_RESULT_REPLY = (
    "לא נמצאו נתונים לשאלה שלך. נסה לנסח אותה מחדש או להרחיב."
)

def _build_history_block(history: list) -> str:
    """Format the last N conversation turns for the prompt context window."""
    if not history:
        return ""
    lines = ["Recent conversation context (for follow-up questions):"]
    for msg in history[-6:]:  # last 6 messages (3 full user↔assistant turns)
        role = "User" if msg.role == "user" else "Assistant"
        lines.append(f"  {role}: {msg.content[:400]}")
    return "\n".join(lines) + "\n\n"

def _format_results_for_reply(results: list, reply_template: str) -> str:
    if not results:
        return _EMPTY_RESULT_REPLY

    if len(results) == 1 and len(results[0]) == 1:
        value = results[0][0]
        try:
            num = float(value)
            formatted = (
                f"{num:,.2f}".rstrip('0').rstrip('.')
                if num % 1 != 0 else f"{int(num):,}"
            )
        except (ValueError, TypeError):
            formatted = str(value)
        return f"{reply_template.rstrip(':').rstrip('.')}: {formatted}"

    def format_val(v):
        if isinstance(v, float):
            return f"{v:.1f}".rstrip('0').rstrip('.')
        return str(v)

    lines = [" • " + " | ".join(format_val(v) for v in row) for row in results[:10]]
    return f"{reply_template.rstrip(':').rstrip('.')}:\n" + "\n".join(lines)

def run_pipeline(question: str, conn, history: list = None) -> dict:
    if history is None:
        history = []

    # Check cache first (only for standalone questions without history context)
    cache_key = question.lower().strip()
    if not history:
        cached = _query_cache.get(cache_key)
        if cached:
            return cached

    schema       = get_schema_description(conn)
    history_block = _build_history_block(history)

    logger.info(f"[pipeline] Question: {_redact_text(question)}")
    prompt = COMBINED_PROMPT_TEMPLATE.format(
        schema=schema, history_block=history_block, question=question
    )

    # LLM call with timeout guard
    raw_response = _call_llm(prompt)

    try:
        parsed  = _parse_llm_json(raw_response)
        sql     = parsed.get("sql")       # None when LLM signals conversational reply
        lead_in = parsed.get("reply", "")
    except ValueError as exc:
        logger.error(f"[pipeline] JSON parse error: {exc}")
        raise SQLValidationError("Failed to generate a valid response format.")

    # ── Conversational path: sql is null → skip DB entirely ───────────────────
    if not sql:
        logger.info("[pipeline] Conversational reply — bypassing DB execution.")
        return {
            "reply":        lead_in,
            "sql_used":     None,
            "row_count":    None,
            "execution_ms": None,
            "columns":      None,
            "raw_results":  None,
        }

    logger.info(f"[pipeline] Generated SQL: {sql}")
    sql = validate_sql(sql)

    t0 = time.perf_counter()
    rows, columns = execute_query(conn, sql)
    execution_ms  = int((time.perf_counter() - t0) * 1000)
    logger.info(f"[pipeline] {len(rows)} rows in {execution_ms}ms")

    final_reply = _format_results_for_reply(rows, lead_in)

    result = {
        "reply":        final_reply,
        "sql_used":     sql,
        "row_count":    len(rows),
        "execution_ms": execution_ms,
        "columns":      columns,
        "raw_results":  [[_serialize_val(v) for v in row] for row in rows],
    }

    # Only cache context-free results (history-dependent queries are ephemeral)
    if not history:
        _query_cache.set(cache_key, result)

    return result


# ─── App + Lifespan ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: Gemini is configured at module level; the DB pool is lazy.
    Nothing to do here except log readiness.

    Shutdown: drain the LLM thread pool gracefully, then close the
    connection pool (returns all connections to Supabase cleanly).
    """
    logger.info("DataLens backend ready (Supabase / PostgreSQL mode).")
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    _llm_executor.shutdown(wait=False)
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
        logger.info("[db] Connection pool closed.")

app = FastAPI(title="DataLens API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    # Authorization must be listed explicitly — browsers will block any
    # request that sends a header not in this allowlist (CORS preflight).
    allow_headers=["Content-Type", "Authorization"],
)


# ─── Models ───────────────────────────────────────────────────────────────────

class HistoryMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    message:    str
    # max_length guards against a history-flood attack that would stuff an
    # enormous prompt into the Gemini token budget and exhaust API quota.
    history:    list[HistoryMessage] = Field(default=[], max_length=20)
    session_id: Optional[str] = None       # if set, DB history is used instead

class ChatResponse(BaseModel):
    status:       str                    # "success" | "error"
    reply:        str
    sql_used:     Optional[str]  = None
    row_count:    Optional[int]  = None
    execution_ms: Optional[int]  = None
    error_code:   Optional[str]  = None
    columns:      Optional[list] = None  # column names for CSV export
    raw_results:  Optional[list] = None  # serialised rows for CSV export
    session_id:   Optional[str]  = None  # echoed back so the frontend can store it

class RawQueryRequest(BaseModel):
    sql: str = Field(
        ...,
        max_length=8_000,
        description=(
            "A PostgreSQL SELECT or WITH query. "
            "Max 8,000 characters — requests beyond this limit are rejected "
            "before any parsing or DB access occurs."
        ),
    )

class SessionCreateRequest(BaseModel):
    channel:    str = Field(default="web", pattern="^(web|whatsapp|telegram|instagram)$")
    contact_id: Optional[str] = None   # phone number, Telegram ID, or browser fingerprint

class SessionCreateResponse(BaseModel):
    session_id: str
    channel:    str
    created_at: str

class MessageOut(BaseModel):
    """One message turn returned by GET /api/sessions/{id}/history."""
    role:       str
    content:    str
    sql_used:   Optional[str] = None
    row_count:  Optional[int] = None
    created_at: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """
    Liveness + DB check. Use this for deployment health probes.
    No auth required — must be publicly reachable by the load balancer.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM posts")
                posts = cur.fetchone()[0]
        return {"status": "ok", "posts_count": posts}
    except Exception as e:
        logger.error(f"[health] DB check failed: {e}")
        return {"status": "degraded", "detail": "DB unavailable"}


@app.get("/db-test")
def db_test():
    """
    Minimal Supabase connectivity probe — SELECT 1 only.
    Useful during initial deployment to verify the connection string and
    pool configuration before running any real queries.
    No auth required so it can be hit from a browser or curl immediately.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ping")
                row = cur.fetchone()
        return {
            "status":  "ok",
            "ping":    row[0],
            "message": "Supabase connection successful.",
        }
    except Exception as e:
        # Detail to server logs only — do not leak driver/DSN internals to clients.
        logger.error(f"[db-test] Connection failed: {e}")
        return {
            "status":  "error",
            "message": "Could not connect to Supabase.",
        }


@app.get("/api/stats", dependencies=[Depends(require_auth)])
def get_stats():
    """Return aggregate row counts for all tables."""
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                results = {}
                for table in ("posts", "comments", "likers", "followers"):
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    results[table] = cur.fetchone()[0]
        return {
            "status":          "success",
            "posts":           results["posts"],
            "comments":        results["comments"],
            "likers":          results["likers"],
            "total_followers": results["followers"],
        }
    except Exception as e:
        logger.error(f"[stats] Query failed: {e}")
        return {"status": "error", "detail": "Could not fetch stats"}


@app.get("/api/schema", dependencies=[Depends(require_auth)])
def get_schema():
    """Expose DB schema so the frontend sidebar stays accurate automatically."""
    with get_db_conn() as conn:
        return {"status": "success", "schema": get_schema_description(conn)}


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
def chat(request: ChatRequest, http_request: Request):
    question  = request.message.strip()
    client_ip = get_client_ip(http_request)

    # ── Guard 1: basic length checks ──────────────────────────────────────────
    if not question:
        return ChatResponse(status="error", reply="Please enter a question.",
                            error_code="validation_error")
    if len(question) > 500:
        return ChatResponse(
            status="error",
            reply="Question too long — please keep it under 500 characters.",
            error_code="validation_error",
        )

    # ── Guard 2: content moderation ───────────────────────────────────────────
    try:
        validate_question(question)
    except InputModerationError as e:
        logger.warning(f"[chat] Moderation block from {client_ip!r}: {e}")
        _audit("moderation_block", ip=client_ip, reason=str(e))
        return ChatResponse(
            status="error",
            reply="Your message contains content that can't be processed. "
                  "Please ask a data analysis question about your Instagram data.",
            error_code="moderation_error",
        )

    # ── Guard 3: per-IP rate limit ─────────────────────────────────────────────
    try:
        check_rate_limit(client_ip)
    except RateLimitError:
        logger.warning(f"[chat] Rate limit hit for {client_ip!r}")
        _audit("rate_limit", ip=client_ip)
        return ChatResponse(
            status="error",
            reply="Too many requests — please wait a moment and try again.",
            error_code="rate_limit_error",
        )

    session_id = request.session_id
    logger.info(f"[chat] {client_ip!r} session={session_id!r}: {_redact_text(question)}")
    _audit("chat_request", ip=client_ip, question=_redact_text(question), session_id=session_id)

    try:
        with get_db_conn() as conn:
            # ── History resolution ────────────────────────────────────────────
            # If the caller supplied a session_id, load the real conversation
            # history from the DB so follow-up questions work after a refresh.
            # Otherwise fall back to the in-memory history sent in the request
            # (backward-compatible with clients that don't use sessions yet).
            if session_id:
                db_msgs = _db_load_history(conn, session_id, limit=12)
                history = [HistoryMessage(role=m["role"], content=m["content"]) for m in db_msgs]
            else:
                history = request.history

            result = run_pipeline(question, conn, history=history)

            # ── Persist messages if a session is active ───────────────────────
            if session_id:
                _db_save_message(conn, session_id, "user", question)
                _db_save_message(
                    conn, session_id, "assistant",
                    result["reply"],
                    sql_used=result.get("sql_used"),
                    row_count=result.get("row_count"),
                )
                _db_touch_session(conn, session_id)
                conn.commit()   # single commit for all three writes

        _audit("chat_success", ip=client_ip,
               row_count=result.get("row_count"),
               ms=result.get("execution_ms"),
               session_id=session_id,
               conversational=result["sql_used"] is None)
        return ChatResponse(status="success", session_id=session_id, **result)

    except SQLValidationError as e:
        # Full detail to server logs only; never echo the rejected SQL / matched
        # rule back to the client (information disclosure).
        logger.warning(f"[chat] SQL validation blocked: {e}")
        _audit("sql_error", ip=client_ip, detail=str(e))
        return ChatResponse(
            status="error",
            reply="I generated a query that isn't allowed for safety reasons. Try rephrasing.",
            error_code="validation_error",
        )

    except psycopg2.Error as e:
        logger.error(f"[chat] PostgreSQL error: {e}")
        _audit("db_error", ip=client_ip, detail=str(e))
        return ChatResponse(
            status="error",
            reply="The database query failed. Try asking in a different way.",
            error_code="db_error",
        )

    except TimeoutError as e:
        logger.error(f"[chat] LLM timeout: {e}")
        _audit("llm_timeout", ip=client_ip)
        return ChatResponse(
            status="error",
            reply="The AI took too long to respond. Please try again.",
            error_code="llm_error",
        )

    except Exception as e:
        # Check for Gemini quota / rate-limit errors first.
        # The new google-genai SDK raises google.genai.errors.ClientError (429).
        # We detect by string rather than importing a specific exception class
        # that varies across SDK versions and may not be installed on Vercel.
        # NOTE: TimeoutError must be caught BEFORE this block (it's a subclass
        # of Exception) — the order of except clauses above is intentional.
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
            logger.warning(f"[chat] Gemini rate limit: {e}")
            _audit("gemini_quota", ip=client_ip)
            return ChatResponse(
                status="error",
                reply="The AI is busy — please wait ~30 seconds and try again.",
                error_code="llm_error",
            )
        logger.error(f"[chat] Unexpected {type(e).__name__}: {e}", exc_info=True)
        _audit("unknown_error", ip=client_ip, error=str(e))
        return ChatResponse(
            status="error",
            reply="Something went wrong on our end. Please try again.",
            error_code="unknown",
        )


@app.post(
    "/api/sessions",
    response_model=SessionCreateResponse,
    dependencies=[Depends(require_auth)],
)
def create_session(request: SessionCreateRequest):
    """
    Create a new persistent conversation session.

    Returns a session_id UUID the frontend stores in localStorage and sends
    with every subsequent /api/chat request to enable history persistence,
    cross-device recall, and eventually GHL CRM sync.
    """
    try:
        with get_db_conn() as conn:
            session_id, created_at = _db_create_session(
                conn, request.channel, request.contact_id
            )
            conn.commit()
        logger.info(f"[sessions] Created session={session_id!r} channel={request.channel!r}")
        return SessionCreateResponse(
            session_id=session_id,
            channel=request.channel,
            created_at=created_at,
        )
    except Exception as e:
        logger.error(f"[sessions] Failed to create session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create session.")


@app.get("/api/sessions/{session_id}/history", dependencies=[Depends(require_auth)])
def get_session_history(
    session_id: str,
    x_session_contact: Optional[str] = Header(default=None),
):
    """
    Load the full message history for a session.

    Used by the frontend on page-load to restore a previous conversation from
    localStorage — the frontend supplies the stored session_id and receives
    back all turns so the chat UI can be reconstructed exactly.

    Ownership guard (R4): web sessions store the frontend's own UUID as
    contact_id at creation time. Callers must echo it back in the
    X-Session-Contact header, or the request is rejected with 403.
    Sessions without a contact_id (Telegram sessions, legacy web sessions
    created before this guard) are still accessible — backward compatible.
    """
    try:
        with get_db_conn() as conn:
            # Verify the session exists and load the ownership token.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT channel, contact_id FROM sessions WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found.")
            channel, contact_id = row[0], row[1]
            # Ownership validation: web sessions with a stored contact_id require
            # the caller to prove they hold that same UUID. hmac.compare_digest
            # prevents timing side-channels on the comparison.
            if channel == "web" and contact_id:
                if not x_session_contact or not hmac.compare_digest(
                    x_session_contact, contact_id
                ):
                    raise HTTPException(status_code=403, detail="Session access denied.")
            messages = _db_load_history(conn, session_id, limit=200)

        return {
            "status":     "success",
            "session_id": session_id,
            "messages":   messages,
        }
    except HTTPException:
        raise   # re-raise 404 as-is; don't wrap it in a 500
    except Exception as e:
        logger.error(f"[sessions] Failed to load history for {session_id!r}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load session history.")


# ─── RAG ─────────────────────────────────────────────────────────────────────

RAG_PROMPT_TEMPLATE = """\
{persona}

=== GROUNDING (FACTS) ===
Answer using ONLY the context excerpts below. Never invent facts about the \
business, prices, services, or availability. If the context does not contain \
the answer, say so warmly and honestly, and offer another way to help. \
Keep it to one or two short paragraphs; no bullet points unless truly needed.

=== CONTEXT FROM KNOWLEDGE BASE ===
{context}

{history_block}=== LANGUAGE RULE ===
Reply in the exact same language as the user's question. \
If the question is in Hebrew, reply in Hebrew. If English, reply in English.

User message: "{question}"
"""


# ─── Telegram triage prompts ("LLM proposes, state machine disposes") ─────────
# These are deliberately SELF-CONTAINED (they do NOT inject persona.system) so
# the Telegram funnel persona is isolated from the web /api/rag_query path. The
# LLM only ever VALIDATES briefly and CLASSIFIES an intent — it never writes the
# call-to-action or transitions the funnel. Code owns every CTA and state change,
# which makes a hallucinated funnel-closure structurally impossible.

_BOT_TRIAGE_PROMPT = """\
You are the warm, grounded front-desk assistant for Erez Gartsman (ארז גרצמן), a \
mentor for relationships, couplehood, and the psychology of dating. You are an \
EMPATHETIC TRIAGE RECEPTIONIST — NOT a therapist. You NEVER analyse, diagnose, or \
try to solve the person's situation in chat, and you never write more than two \
short sentences. Your goal is to make the person feel heard, then connect them to \
Erez.

STEP 1 — Write a short reply (ONE or TWO sentences, at eye level, no advice, no \
analysis, no lists).

STEP 2 — Classify the message into exactly one "intent":
  • "EMOTIONAL" — the person shares anything personal, emotional, or relational \
    (a struggle, a feeling, a story). Your reply VALIDATES the feeling briefly. \
    The system will then proactively offer a consultation — so keep your \
    validation pointed toward "you deserve real support".
  • "FAQ" — a factual/logistical question (price/cost, how it works, hours, what \
    the services are, who Erez is). Answer briefly from the context; the system \
    will then offer to schedule.
  • "SMALLTALK" — a greeting, thanks, or clearly off-topic chit-chat where an \
    offer would feel pushy. Reply briefly; NO offer will be added.

PRICE/COST: If asked about price or cost and the context has no exact figure, do \
NOT say "I don't know". Say, warmly and in the user's language: "העלות המדויקת \
תלויה בסוג התהליך, והצוות יעביר את כל הפרטים כשייצרו איתך קשר" (or its equivalent). \
Classify such messages as "FAQ".

GROUNDING: For any factual claim about Erez, services, or availability, use ONLY \
the context excerpts below. Never invent facts.

{recall_block}=== CONTEXT FROM KNOWLEDGE BASE ===
{context}

{history_block}=== LANGUAGE ===
Reply in the SAME language as the user (Hebrew → Hebrew).

=== EXAMPLES (format only) ===
User: "בעלי בגד בי ואני מרגישה שבורה" → \
{{"reply": "אני שומע כמה זה כואב, ומגיע לך מקום בטוח להישען בו.", "intent": "EMOTIONAL"}}
User: "כמה עולה שיחה עם ארז?" → \
{{"reply": "העלות תלויה בסוג התהליך, והצוות יעביר את כל הפרטים כשייצרו איתך קשר.", "intent": "FAQ"}}
User: "תודה רבה!" → {{"reply": "תמיד בשמחה 🤍", "intent": "SMALLTALK"}}

=== OUTPUT — STRICT JSON, NOTHING ELSE ===
Return ONLY one JSON object, no markdown fences:
{{"reply": "<your 1-2 sentence reply>", "intent": "EMOTIONAL" or "FAQ" or "SMALLTALK"}}
Rules: "reply" is at most two short sentences. Do NOT mention booking, a meeting, \
or any call-to-action inside "reply" — the SYSTEM appends that. Double-quoted keys \
and values only. No trailing commas. No text outside the JSON object.

User message: "{question}"
"""

_BOT_OFFER_RESPONSE_PROMPT = """\
Context: Erez's assistant has just offered the user a personal consultation with \
Erez. Read the user's reply and classify it.

DECISION:
• "AFFIRM"  — the user agrees, accepts, or shows willingness (e.g. "אשמח", "כן", \
  "בטח", "נשמע טוב", "למה לא", "בוא/י נעשה את זה"). Any positive/willing answer.
• "DECLINE" — the user clearly refuses or opts out ("לא", "לא עכשיו", \
  "לא מעוניין", "stop").
• "OTHER"   — neither a clear yes nor no: they ask a question, hesitate \
  ("אני לא בטוחה", "אולי", "תני לי לחשוב"), or keep sharing more.

{history_block}=== LANGUAGE ===
Reply in the SAME language as the user.

=== OUTPUT — STRICT JSON, NOTHING ELSE ===
{{"decision": "AFFIRM" or "DECLINE" or "OTHER", "reply": "<see below>"}}
- For OTHER: ONE short warm sentence that acknowledges and gently re-invites \
  (do NOT solve or analyse).
- For DECLINE: ONE short, no-pressure sentence.
- For AFFIRM: an empty string "".
Double-quoted keys and values only. No trailing commas. No text outside the JSON.

User reply: "{question}"
"""


class RagQueryRequest(BaseModel):
    message:    str
    session_id: Optional[str] = None   # optional — for session-aware RAG in the future

class RagQueryResponse(BaseModel):
    status:    str
    reply:     str
    sources:   list[str]               # source filenames used (shown as citations in UI)
    error_code: Optional[str] = None


def _embed_text(text: str) -> list[float]:
    """
    Embed a single string using gemini-embedding-001, truncated to 768 dims.

    Must use output_dimensionality=768 to match the VECTOR(768) column in
    knowledge_base — the model defaults to 3072 dims without this config.
    """
    response = _gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=genai_types.EmbedContentConfig(output_dimensionality=768),
    )
    return response.embeddings[0].values


def _retrieve_chunks(conn, query_vector: list[float], top_k: int = 5) -> list[dict]:
    """
    Run a pgvector cosine similarity search and return the top_k most relevant
    knowledge_base chunks with their similarity scores and source filenames.

    The <=> operator is cosine *distance* (0 = identical, 2 = opposite), so
    similarity = 1 - distance.  We filter out low-relevance rows to avoid
    injecting completely irrelevant context into the prompt.

    THRESHOLD NOTE (root cause of the "always returns no info" prod bug):
    gemini-embedding-001 truncated to 768 dims (Matryoshka) produces a
    similarity distribution that is shifted noticeably lower than the
    normalised 3072-dim space — genuinely relevant chunks routinely score in
    the ~0.30–0.45 band rather than ~0.60+. The previous 0.50 floor therefore
    rejected every row and the endpoint always replied "no relevant info."
    0.25 keeps obvious garbage out while letting real matches through; the
    top_k + ORDER BY already guarantee we only ever take the closest rows.
    """
    vec_str = f"[{','.join(str(v) for v in query_vector)}]"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT content, source,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM   knowledge_base
            ORDER  BY embedding <=> %s::vector
            LIMIT  %s
            """,
            (vec_str, vec_str, top_k),
        )
        rows = cur.fetchall()

    return [
        {"content": r[0], "source": r[1], "similarity": float(r[2])}
        for r in rows
        if float(r[2]) >= 0.25   # relevance threshold — calibrated for 768-dim gemini-embedding-001
    ]


def _build_rag_history_block(history: list) -> str:
    """
    Format recent conversation turns (dicts from _db_load_history, oldest→newest)
    into a context block for the RAG prompt so the assistant has short-term
    memory. Returns "" when there is no history — the web /api/rag_query path
    passes nothing, so its prompt is byte-for-byte unchanged.
    """
    if not history:
        return ""
    lines = ["=== RECENT CONVERSATION (most recent last; for context only) ==="]
    for m in history[-6:]:   # last 6 messages ≈ 3 user↔assistant turns
        role    = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "")[:400]
        lines.append(f"{role}: {content}")
    return "\n".join(lines) + "\n\n"


def _rag_generate(question: str, chunks: list, history: list = None) -> tuple:
    """
    Turn retrieved knowledge-base chunks into a grounded answer. Does NO database
    access, so it is deliberately called *after* the pooled connection has been
    released — the slow Gemini call never holds a connection. Returns
    (reply, sources). Shared by /api/rag_query and the Telegram webhook.
    """
    if not chunks:
        is_hebrew = any(ord(c) > 0x590 for c in question)
        reply = (
            "לא נמצא מידע רלוונטי במאגר הידע שלנו לשאלה זו. נסה לנסח מחדש."
            if is_hebrew else
            "No relevant information found in the knowledge base for your question. Try rephrasing."
        )
        return reply, []

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk["source"] or "unknown"
        context_parts.append(f"[{i}] (from {source}):\n{chunk['content']}")
    context = "\n\n".join(context_parts)

    prompt = RAG_PROMPT_TEMPLATE.format(
        persona=_get_config("persona.system"),
        context=context,
        history_block=_build_rag_history_block(history or []),
        question=question,
    )
    reply   = _call_llm(prompt)
    sources = sorted({c["source"] for c in chunks if c["source"]})
    return reply, sources


# ─── Telegram triage engine ───────────────────────────────────────────────────
# Used ONLY by the Telegram webhook (the web /api/rag_query path keeps using
# _rag_generate above, unchanged). The LLM returns structured JSON; the webhook
# state machine is the sole actuator of CTAs and state transitions.

_BOT_REPLY_MAX_CHARS = 320   # hard brevity backstop — even prompt drift can't wall-of-text

# Last-resort warm line if the model returns an empty reply.
_BOT_FALLBACK_REPLY = "אני כאן ואיתך 🤍 ספרו לי עוד על מה שעובר עליכם."


def _truncate_reply(text: str) -> str:
    """
    Enforce the triage brevity contract structurally. Cuts at a sentence/word
    boundary near the cap so a verbose answer can never reach the user as a wall
    of text, regardless of what the LLM produced.
    """
    t = (text or "").strip()
    if len(t) <= _BOT_REPLY_MAX_CHARS:
        return t
    cut = t[:_BOT_REPLY_MAX_CHARS]
    # Prefer the last sentence end; otherwise the last space.
    boundary = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"),
                   cut.rfind("\n"), cut.rfind("…"))
    if boundary < _BOT_REPLY_MAX_CHARS // 2:
        boundary = cut.rfind(" ")
    return (cut[:boundary + 1] if boundary > 0 else cut).strip() + " …"


def _bot_triage_reply(question: str, chunks: list, history: list = None,
                      recall_block: str = "") -> tuple:
    """
    One triage turn: the LLM validates briefly and classifies the intent.
    Returns (reply, intent, sources) where intent ∈ {"OFFER_MEETING", "ANSWER"}.

    recall_block (Hook F, memory.recall_enabled): pre-built person-memory
    context from nexus.memory.build_recall_block — "" (the default) leaves the
    prompt byte-for-byte unchanged, so recall OFF means literally no change.

    FAIL-SAFE: on any JSON/parse failure we degrade to a plain ANSWER (send the
    text, change no state) — we never crash and never fabricate an OFFER, so a
    parsing glitch can't spuriously enter or skip the funnel.
    """
    if chunks:
        context = "\n\n".join(
            f"[{i}] (from {c['source'] or 'unknown'}):\n{c['content']}"
            for i, c in enumerate(chunks, 1)
        )
    else:
        context = "(no specific knowledge-base match — lead with warmth.)"

    prompt = _BOT_TRIAGE_PROMPT.format(
        recall_block=recall_block or "",
        context=context,
        history_block=_build_rag_history_block(history or []),
        question=question,
    )
    raw = _call_llm(prompt)
    sources = sorted({c["source"] for c in chunks if c["source"]})

    try:
        parsed = _parse_llm_json(raw)
        reply  = _truncate_reply(parsed.get("reply") or "")
        intent = parsed.get("intent")
        if intent not in ("EMOTIONAL", "FAQ", "SMALLTALK"):
            # Parsed but unknown label → treat as substantive (offer) per the
            # lead-gen bias rather than dropping the user.
            intent = "FAQ"
    except (ValueError, AttributeError) as e:
        # Total parse glitch: send the raw text as SMALLTALK (no funnel) — we
        # never fabricate intent or force an offer on uncertain output.
        logger.warning(f"[triage] JSON parse failed, degrading to SMALLTALK: {e}")
        reply, intent = _truncate_reply(raw), "SMALLTALK"

    return (reply or _BOT_FALLBACK_REPLY), intent, sources


# Stable phrase from _TG_MEETING_CTA, used to recognise that our most recent
# message was an offer (so a later "אשמח" can be honoured even if the
# offered_meeting state was lost — e.g. the 24h bot_state TTL expired).
_OFFER_MARKER = "לחבר אתכם לארז"

def _last_bot_message_offered(history: list) -> bool:
    """True if the most recent assistant message in history was a meeting offer."""
    for m in reversed(history or []):
        if m.get("role") == "assistant":
            return _OFFER_MARKER in (m.get("content") or "")
    return False


def _bot_classify_offer_response(question: str, history: list = None) -> tuple:
    """
    Interpret the user's reply to an offered meeting. Returns (decision, reply)
    with decision ∈ {"AFFIRM", "DECLINE", "OTHER"}.

    A short, obvious yes/no is resolved instantly (no LLM round-trip); everything
    else is classified by the LLM IN CONTEXT — robust to any natural phrasing,
    not a brittle keyword list. FAIL-SAFE: a parse failure degrades to "OTHER"
    (re-offer), never a false capture or false close.
    """
    if _is_affirmation(question):
        return "AFFIRM", ""
    if _is_escape_intent(question):        # short, length-guarded opt-out
        return "DECLINE", ""

    prompt = _BOT_OFFER_RESPONSE_PROMPT.format(
        history_block=_build_rag_history_block(history or []),
        question=question,
    )
    raw = _call_llm(prompt)
    try:
        parsed   = _parse_llm_json(raw)
        decision = parsed.get("decision")
        reply    = _truncate_reply(parsed.get("reply") or "")
        if decision not in ("AFFIRM", "DECLINE", "OTHER"):
            decision = "OTHER"
    except (ValueError, AttributeError) as e:
        logger.warning(f"[triage] offer-response parse failed, degrading to OTHER: {e}")
        decision, reply = "OTHER", ""
    return decision, reply


@app.post(
    "/api/rag_query",
    response_model=RagQueryResponse,
    dependencies=[Depends(require_auth)],
)
def rag_query(request: RagQueryRequest, http_request: Request):
    """
    Knowledge-base Q&A via RAG.

    Pipeline:
      1. Embed the user's question with Gemini gemini-embedding-001 (768 dims).
      2. Retrieve the top-5 most similar chunks from knowledge_base (pgvector).
      3. Inject chunks as context into a grounded Gemini prompt.
      4. Return the answer + source filenames for UI citation display.
    """
    client_ip = get_client_ip(http_request)
    question  = request.message.strip()

    if not question:
        return RagQueryResponse(
            status="error", reply="Please enter a question.", sources=[],
            error_code="validation_error",
        )
    if len(question) > 500:
        return RagQueryResponse(
            status="error",
            reply="Question too long — keep it under 500 characters.",
            sources=[],
            error_code="validation_error",
        )

    # Crisis check runs BEFORE moderation: a user in distress must get the
    # compassionate response, never the cold "can't process this" block.
    if is_crisis(question):
        _audit("rag_crisis", ip=client_ip)
        return RagQueryResponse(
            status="success", reply=_get_config("crisis.message"), sources=[],
        )

    try:
        validate_question(question)
    except InputModerationError as e:
        _audit("rag_moderation_block", ip=client_ip, reason=str(e))
        return RagQueryResponse(
            status="error",
            reply="Your message contains content that can't be processed.",
            sources=[],
            error_code="moderation_error",
        )

    try:
        check_rate_limit(client_ip)
    except RateLimitError:
        return RagQueryResponse(
            status="error",
            reply="Too many requests — please wait a moment.",
            sources=[],
            error_code="rate_limit_error",
        )

    _audit("rag_request", ip=client_ip, question=_redact_text(question))

    try:
        # Embed first, then hold the pooled connection only for the vector
        # search — _rag_generate() runs the slow Gemini call with no connection
        # checked out.
        query_vector = _embed_text(question)
        with get_db_conn() as conn:
            chunks = _retrieve_chunks(conn, query_vector, top_k=5)

        reply, sources = _rag_generate(question, chunks)
        _audit("rag_success", ip=client_ip, sources=sources, chunks=len(chunks))
        return RagQueryResponse(status="success", reply=reply, sources=sources)

    except TimeoutError:
        logger.error("[rag] LLM timeout")
        return RagQueryResponse(
            status="error",
            reply="The AI took too long to respond. Please try again.",
            sources=[],
            error_code="llm_error",
        )
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str:
            return RagQueryResponse(
                status="error",
                reply="The AI is busy — please wait ~30 seconds and try again.",
                sources=[],
                error_code="llm_error",
            )
        logger.error(f"[rag] Unexpected {type(e).__name__}: {e}", exc_info=True)
        return RagQueryResponse(
            status="error",
            reply="Something went wrong. Please try again.",
            sources=[],
            error_code="unknown",
        )


# ─── Telegram Bot Webhook ─────────────────────────────────────────────────────
# MVP: the bot is strictly the RAG "Erez representative". It only ever answers
# from the knowledge base — it never generates SQL or touches the Instagram
# analytics tables. Conversation memory is persisted in the existing sessions /
# messages tables, keyed by the Telegram chat_id (no schema migration needed).

# ─── Lead capture ─────────────────────────────────────────────────────────────

# Booking-intent detector — fires the deterministic funnel ONLY for an explicit
# scheduling request. It deliberately excludes FAQ / price / consultation-info
# vocabulary (מחיר, "כמה עולה", ייעוץ, consultation, session): those are
# questions, not booking requests, and must flow to the triage engine to be
# answered (and then pivoted to a CTA) — never short-circuited into the funnel.
# "פגיש\w*" covers פגישה / פגישת / פגישות / לפגישה.
_BOOKING_INTENT = re.compile(
    r"(פגיש\w*|לקבוע|לתאם|קביעת\s*תור|להירשם|הרשמה|שיחה\s*אישית|"
    r"לדבר\s*עם\s*ארז|ליצור\s*קשר|לפגוש|\bתור\b|"
    r"book|booking|appointment|schedule|sign\s*up)",
    re.IGNORECASE,
)

# Israeli phone regex — matches 05X-XXXXXXX and international +9725XXXXXXXX
_IL_PHONE = re.compile(r"(?:\+?972|0)5[0-9][-\s]?\d{3}[-\s]?\d{4}")

# Contact-share keyboard (one-time, resizes to the reply bar)
_CONTACT_KEYBOARD = {
    "keyboard":             [[{"text": "📱 שתפו את המספר שלי", "request_contact": True}]],
    "resize_keyboard":      True,
    "one_time_keyboard":    True,
    "input_field_placeholder": "לחצו על הכפתור לשיתוף המספר",
}
_REMOVE_KEYBOARD = {"remove_keyboard": True}

# ── State machine constants ────────────────────────────────────────────────────
_BOT_STATE_TTL_HOURS = 24   # states older than this are treated as NULL on load
_MAX_CONTACT_RETRIES = 3    # non-phone, non-escape replies before graceful exit

# User explicitly opts out of the current funnel step.
_TG_ESCAPE_RESPONSE = (
    "בסדר גמור 😊 אם תרצו לחזור לנושא בעתיד — אני כאן. "
    "אפשר גם לשאול כל שאלה אחרת."
)
# Shown after MAX_CONTACT_RETRIES non-phone replies in awaiting_contact.
_TG_CONTACT_RETRY_EXHAUSTED = (
    "ממש בסדר, ללא לחץ 😊 אם תחליטו שתרצו שארז יחזור אליכם — "
    "פשוט שלחו את המספר בכל עת ואשמח לעזור."
)

# Regex: user wants to exit the current funnel state.
# Checked before validate_question so short signals like "לא" (2 chars) are caught
# before the length guard rejects them.
_ESCAPE_INTENT = re.compile(
    r"\b(לא\b|בטל|עצור|הפסק|שנה\s*נושא|לא\s*רלוונטי|לא\s*עכשיו|"
    r"דילוג|שכח|ignore|stop|cancel|never\s*mind|not\s*now|skip|back)\b",
    re.IGNORECASE,
)

# A genuine opt-out is SHORT ("לא", "לא עכשיו", "stop", "never mind"). A long
# message that merely contains a negative word ("הוא לא נתן לי סיבה ואני לא
# אסמוך שוב…") is a real answer, not a cancellation. Capping the word count is
# what stops emotional venting from being misread as a refusal anywhere the
# escape gate is consulted.
_ESCAPE_MAX_WORDS = 4

def _is_escape_intent(text: str) -> bool:
    """
    True only when the message is a SHORT, clear opt-out from the current funnel
    step. Substantive messages (more than _ESCAPE_MAX_WORDS words) are treated as
    content, never as an opt-out — so a long emotional story can never trip the
    cancellation path even if it contains words like "לא"/"stop".
    """
    t = (text or "").strip()
    if not t or len(t.split()) > _ESCAPE_MAX_WORDS:
        return False
    return bool(_ESCAPE_INTENT.search(t))


# Obvious-affirmation fast-path for the offered_meeting turn. This is ONLY a
# latency optimisation for unmistakable short replies — the LLM classifier in
# _bot_classify_offer_response is the authoritative, natural-language-robust
# detector. Length-guarded (same as escape) so a long message always goes to
# the LLM rather than matching on a single word.
_AFFIRM_INTENT = re.compile(
    r"(\bכן\b|אשמח|בשמחה|בטח|סבבה|יאללה|בהחלט|נשמע\s*טוב|בוא[יו]?\s*נעשה|"
    r"\bok\b|\bokay\b|\byes\b|\bsure\b|sounds\s*good)",
    re.IGNORECASE,
)

def _is_affirmation(text: str) -> bool:
    """True for a SHORT, unmistakable acceptance (fast-path only; LLM is primary)."""
    t = (text or "").strip()
    if not t or len(t.split()) > _ESCAPE_MAX_WORDS:
        return False
    return bool(_AFFIRM_INTENT.search(t))


def _make_contact_state(retry: int = 0) -> str:
    """Encode the awaiting_contact state with its retry counter."""
    return f"awaiting_contact:{retry}"

def _is_awaiting_contact(state: str | None) -> bool:
    """True for any awaiting_contact:N state (including legacy bare string)."""
    return bool(state and state.startswith("awaiting_contact"))

def _parse_contact_retry(state: str | None) -> int:
    """Extract the retry count from 'awaiting_contact:N'. Returns 0 for any edge case."""
    try:
        return int((state or "").split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


# ── offered_meeting state — the bot has offered a consultation and is awaiting
#    the user's response. Encodes a re-offer counter so we never nag. (bot_state
#    is TEXT, so this new value needs no DB migration.) ──────────────────────────
_MAX_REOFFERS = 2

def _make_offer_state(n: int = 0) -> str:
    return f"offered_meeting:{n}"

def _is_offered_meeting(state: str | None) -> bool:
    return bool(state and state.startswith("offered_meeting"))

def _parse_offer_count(state: str | None) -> int:
    try:
        return int((state or "").split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def _format_lead_thanks(name: str | None) -> str:
    """
    Build the lead confirmation message without a double-space when no name is
    given (a naive "תודה {name} 🙏".format(name='') would yield a double space);
    this helper inserts 'name + space' only when a non-empty name is available.
    """
    prefix = f"{name.strip()} " if name and name.strip() else ""
    return (
        f"תודה {prefix}🙏 הפנייה התקבלה וארז יחזור אליכם בהקדם. "
        f"בינתיים, אם יש עוד שאלות — אני כאן."
    )


_TG_QUALIFICATION_QUESTION = (
    "בשמחה. כדי שנוכל לבדוק אם ארז הוא הכתובת המדויקת עבורך, "
    "נשמח לשמוע בכמה מילים על מה תרצו לדבר?"
)
_TG_QUALIFICATION_ACK = (
    "תודה על השיתוף 🙏 ממה שעלה, נראה שיש מקום ממשי לעבוד על זה יחד. "
    "נשמח לקבל פרטי קשר כדי שארז יוכל לחזור אליכם:"
)
# Code-owned call-to-action appended after the LLM's brief validation when the
# triage step chooses OFFER_MEETING. The LLM is explicitly told NOT to write this
# itself — so the offer can never be hallucinated or malformed.
_TG_MEETING_CTA = (
    "אם זה מרגיש לכם נכון, אשמח לחבר אתכם לארז לשיחה אישית ורגועה — "
    "רוצים שאתאם?"
)
# Preamble shown with the contact keyboard once the user accepts the offer.
_TG_OFFER_ACK = (
    "יופי, אני שמח 🙏 רק נשאיר פרטים קצרים כדי שארז יחזור אליכם בעצמו:"
)
# No-pressure step-back when the user declines the offer.
_TG_OFFER_DECLINED = (
    "לגמרי בסדר, בלי שום לחץ 😊 אני כאן להמשיך לדבר על מה שתרצו, "
    "ואם תרצו לחזור לזה בעתיד — פשוט תגידו."
)
# Gentle close after the re-offer cap, so we never nag.
_TG_OFFER_BACKOFF = (
    "אני כאן בכל רגע שתרצו 🤍 אפשר להמשיך לדבר, ומתי שתהיו מוכנים — נתאם."
)
# Gentle redirect when the user types text (e.g. "כן") instead of tapping the
# contact button while bot_state == 'awaiting_contact'.
_TG_AWAITING_CONTACT_RETRY = (
    "אנא לחצו על הכפתור למטה כדי לשתף את המספר, "
    "או פשוט הקלידו אותו כאן:"
)
# Keyboard UX instructions: explicitly directs users past the standard keyboard
# that Telegram opens when they tap the reply bar — a known UX trap.
_TG_CONTACT_PROMPT = (
    "רגע לפני שנמשיך – תרצו שארז ייצור קשר אישית? "
    "לחצו על הכפתור הגדול 'שתף איש קשר' שמופיע כאן למטה 👇 "
    "(אם קפצה לכם מקלדת רגילה והכפתור נעלם, לחצו על סמל הריבועים הקטן "
    "בצד שורת ההודעה כדי להחזיר אותו)."
)

# Deterministic reply for a user we ALREADY captured who shows booking intent
# again. already_lead suppresses the qualification funnel, so without this the
# message falls through to the generic RAG model — which has no booking script
# and tends to ramble. This fixed, on-brand line confirms we have their details
# and invites a short topic note, skipping the LLM entirely.
_TG_ALREADY_LEAD_BOOKING = (
    "הפרטים שלכם כבר אצלנו 🙏 ארז יחזור אליכם בהקדם לתיאום. "
    "אם תרצו, אפשר להשאיר כאן בכמה מילים על מה תרצו להתמקד בשיחה — "
    "וזה יעזור לארז להגיע מוכן. בינתיים אני כאן לכל שאלה."
)


def _has_booking_intent(text: str) -> bool:
    """True when the user's message suggests interest in booking / consultation."""
    return bool(_BOOKING_INTENT.search(text or ""))


def _extract_phone_from_text(text: str) -> str | None:
    """Regex fallback: pull an Israeli phone number out of free text."""
    m = _IL_PHONE.search(text or "")
    return m.group(0).replace(" ", "").replace("-", "") if m else None


def _build_intent_summary(history: list, last_text: str) -> str:
    """
    One-liner intent summary for the owner alert, built from the last 3 user
    turns so Erez sees what the conversation was about at a glance.
    """
    user_msgs = [m.get("content", "") for m in history if m.get("role") == "user"]
    user_msgs.append(last_text)
    parts = [m.strip()[:80] for m in user_msgs[-3:] if m.strip()]
    return " | ".join(parts)[:300]


def _db_has_lead(conn, chat_id_str: str, channel: str = "telegram") -> bool:
    """True if we already captured a lead from this user on the given channel."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM leads WHERE channel = %s AND chat_id = %s LIMIT 1",
            (channel, chat_id_str),
        )
        return cur.fetchone() is not None


def _db_get_or_create_channel_session(conn, channel: str, contact_id: str) -> str:
    """
    Generic session-ID resolver for any channel (telegram, instagram, …).
    Reuses the sessions table UNIQUE(channel, contact_id) index — same race-safe
    INSERT … ON CONFLICT … RETURNING pattern as the Telegram-specific helper.
    Caller owns the commit.

    NEXUS Hook A: when the session has no person_id yet, resolve/create the
    canonical person and stamp it. The hook is SAVEPOINT-guarded inside
    nexus.hooks — it can never raise and never aborts the caller's
    transaction; on failure person_id simply stays NULL and the next turn
    retries (self-healing). Once stamped, the hook is skipped entirely, so
    routine message turns pay zero extra writes.
    """
    person_id = None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, person_id FROM sessions "
            "WHERE channel = %s AND contact_id = %s LIMIT 1",
            (channel, contact_id),
        )
        row = cur.fetchone()
        if row:
            session_id, person_id = str(row[0]), row[1]
        else:
            cur.execute(
                """
                INSERT INTO sessions (channel, contact_id)
                VALUES (%s, %s)
                ON CONFLICT (channel, contact_id) DO NOTHING
                RETURNING id
                """,
                (channel, contact_id),
            )
            inserted = cur.fetchone()
            if inserted:
                session_id = str(inserted[0])
            else:
                # Concurrent request won the insert — re-select.
                cur.execute(
                    "SELECT id, person_id FROM sessions "
                    "WHERE channel = %s AND contact_id = %s LIMIT 1",
                    (channel, contact_id),
                )
                row = cur.fetchone()
                session_id, person_id = str(row[0]), row[1]

    if person_id is None:
        nexus_hooks.on_channel_session(conn, session_id, channel, contact_id)
    return session_id


def _db_get_session_state(conn, session_id: str) -> str | None:
    """
    Return the bot_state for a session, or None when unset, not found, or expired.

    TTL check: if bot_state_expires_at < NOW() the state is treated as NULL.
    The stale value stays in the DB until the next _db_set_session_state call
    clears it — no extra write on the read path (important for serverless).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bot_state, bot_state_expires_at FROM sessions WHERE id = %s",
            (session_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    bot_state, expires_at = row[0], row[1]
    if expires_at and expires_at < datetime.datetime.now(datetime.timezone.utc):
        logger.info(f"[state] Expired bot_state={bot_state!r} for session {session_id[:8]}")
        return None   # expired — caller will clear on next write
    return bot_state


def _db_set_session_state(conn, session_id: str, state: str | None) -> None:
    """
    Write bot_state for a session and maintain its TTL.

    Setting a non-None state also writes bot_state_expires_at = NOW() + 24 h so
    a user who started the qualification funnel and went idle for a day returns
    to a clean conversation instead of being trapped in a stale state.
    Passing None clears both columns. Caller must commit.
    """
    with conn.cursor() as cur:
        if state is None:
            cur.execute(
                "UPDATE sessions SET bot_state = NULL, bot_state_expires_at = NULL "
                "WHERE id = %s",
                (session_id,),
            )
        else:
            cur.execute(
                "UPDATE sessions "
                "SET bot_state = %s, "
                "    bot_state_expires_at = NOW() + INTERVAL '%s hours' "
                "WHERE id = %s",
                (state, _BOT_STATE_TTL_HOURS, session_id),
            )


def _db_save_lead(
    conn,
    session_id: str,
    chat_id: str,
    name: str,
    phone: str,
    intent_summary: str,
    channel: str = "telegram",
) -> str | None:
    """
    Insert a new lead row and return its UUID, or None if this user already
    has a lead (ON CONFLICT DO NOTHING on the UNIQUE(channel, chat_id) index).
    Caller must commit.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO leads (session_id, chat_id, channel, name, phone, intent_summary)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (channel, chat_id) DO NOTHING
            RETURNING id
            """,
            (session_id, chat_id, channel, name or None, phone, intent_summary or None),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _db_mark_lead_notified(conn, lead_id: str) -> None:
    """Stamp notified_at so we never DM the owner twice for the same lead."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE leads SET notified_at = NOW() WHERE id = %s AND notified_at IS NULL",
            (lead_id,),
        )


def _db_set_lead_alert_message_id(conn, lead_id: str, message_id) -> None:
    """Persist the Telegram message_id of the capture alert so the later brief
    pass can edit that same message in place (single evolving alert)."""
    if not message_id:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE leads SET alert_message_id = %s WHERE id = %s",
            (str(message_id), lead_id),
        )


def _format_lead_alert(name: str, phone: str, intent_summary: str, chat_id: str,
                       channel: str = "telegram", username: Optional[str] = None,
                       brief: Optional[dict] = None) -> str:
    """
    Build the owner-alert text. Shared by the instant capture alert (brief=None)
    and the later edit-in-place enrichment (brief=<dict>), so the evolving message
    is formatted in exactly one place.

    Channel rules:
      • Telegram shows the "נושא" line (it has real conversation history).
      • Instagram omits "נושא" at capture (it would only echo the generic
        Icebreaker text); the real topic arrives via the appended brief.
      • Link: Telegram → tg://user?id=…, Instagram → ig.me/m/<username> (or IGSID).
    """
    now_str  = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")
    name_str = name or (f"@{username}" if channel == "instagram" and username
                        else "לא צוין")
    label    = {"instagram": "📸 אינסטגרם", "telegram": "✈️ טלגרם"}.get(channel, channel)

    lines = [
        f"🔔 ליד חדש — {label}",
        "",
        f"👤 שם: {name_str}",
        f"📱 טלפון: {phone}",
    ]
    # "נושא" is meaningful only for Telegram; for Instagram it's the Icebreaker echo.
    if channel != "instagram":
        lines.append(f"💬 נושא: {intent_summary or '—'}")
    lines.append(f"🕐 {now_str}")
    lines.append("")
    if channel == "telegram":
        lines.append(f"לפתיחת השיחה: tg://user?id={chat_id}")
    elif username:
        lines.append(f"לפתיחת השיחה: https://ig.me/m/{username}  (@{username})")
    else:
        lines.append(f"מזהה אינסטגרם (IGSID): {chat_id}")

    # Appended only on the edit-in-place enrichment pass.
    if brief:
        urgency = brief.get("urgency")
        lines += [
            "",
            "🧠 תקציר ליד",
            f"📌 נושא: {brief.get('topic') or '—'}",
            f"❤️ מצב: {brief.get('emotional_state') or '—'}",
            f"⚡ דחיפות: {urgency}/5" if urgency else "⚡ דחיפות: —",
            f"🗣️ פתיח מוצע: {brief.get('opening') or '—'}",
        ]
    return "\n".join(lines)


def _alert_owner(lead_id: str, name: str, phone: str, intent_summary: str,
                 chat_id: str, channel: str = "telegram",
                 username: Optional[str] = None):
    """
    Instantly DM Erez on Telegram with the structured lead details. Best-effort —
    a delivery failure is logged but never propagated. Returns the sent Telegram
    message_id (so it can be persisted and later edited to append the brief), or
    None if the alert was skipped / failed.
    """
    if not settings.telegram_owner_chat_id:
        logger.warning("[leads] TELEGRAM_OWNER_CHAT_ID not set — owner alert skipped.")
        return None

    text = _format_lead_alert(name, phone, intent_summary, chat_id, channel, username)
    message_id = _send_telegram_message(settings.telegram_owner_chat_id, text)
    logger.info(f"[leads] Owner alerted for lead {lead_id} ({channel}) "
                f"msg_id={message_id}")
    return message_id


# ─── CRM lead sync — swappable provider adapter ───────────────────────────────
# Supabase is the source of truth; the CRM is a downstream projection. The sync
# destination lives behind a single _crm_sync_lead() interface selected by
# settings.crm_provider, so the vendor (HubSpot today) is an implementation
# detail — swap providers by changing one env var, and run credential-free with
# the "fake" provider in tests/local dev. Every call is BEST-EFFORT: a failure
# logs and returns None but never raises, so the user's chat reply is never
# affected. Leads that don't sync keep crm_synced_at = NULL and are retried by
# /api/cron/crm-sync. Uses stdlib urllib only (no SDK) to keep the bundle small.

_HUBSPOT_BASE = "https://api.hubapi.com"
_hubspot_pipeline_cache: Optional[tuple] = None   # (pipeline_id, stage_id), discovered once


def _crm_enabled() -> bool:
    """True when a usable provider is configured."""
    if settings.crm_provider == "hubspot":
        return _hubspot_enabled()
    if settings.crm_provider == "fake":
        return True
    return False


def _crm_sync_lead(name: Optional[str], phone: str,
                   intent_summary: Optional[str],
                   channel: str = "telegram",
                   external_user_id: Optional[str] = None,
                   username: Optional[str] = None) -> Optional[str]:
    """Dispatch a lead push to the configured provider. Returns the external id."""
    if not _crm_enabled():
        return None
    if settings.crm_provider == "fake":
        return _fake_sync_lead(name, phone, intent_summary)
    return _hubspot_sync_lead(name, phone, intent_summary, channel,
                              external_user_id, username)


def _fake_sync_lead(name: Optional[str], phone: str,
                    intent_summary: Optional[str]) -> Optional[str]:
    """In-memory provider for tests / local dev — deterministic id, no network."""
    external_id = f"fake-{abs(hash(phone)) % 10**8:08d}"
    logger.info(f"[crm] (fake) synced lead → {external_id}")
    return external_id


def _crm_format_phone(phone: str) -> str:
    """Best-effort E.164 normalisation (Israeli-aware) for stable CRM matching."""
    p = (phone or "").strip().replace(" ", "").replace("-", "")
    if not p:
        return p
    if p.startswith("+"):
        return p
    if p.startswith("0") and len(p) == 10:   # local 05X-XXXXXXX
        return "+972" + p[1:]
    if p.startswith("972"):
        return "+" + p
    return "+" + p


# ── HubSpot provider ──────────────────────────────────────────────────────────

def _hubspot_enabled() -> bool:
    return bool(settings.hubspot_private_token)


def _hubspot_request(method: str, path: str,
                     payload: Optional[dict] = None) -> Optional[dict]:
    """
    One authenticated HubSpot v3 request. Returns parsed JSON on success or None
    on any error (logged, never raised). 10 s timeout keeps the webhook within
    the same budget as Telegram sends.
    """
    url = f"{_HUBSPOT_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {settings.hubspot_private_token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        logger.error(f"[crm] HubSpot {method} {path} → HTTP {e.code}: {detail}")
        return None
    except Exception as e:
        logger.error(f"[crm] HubSpot {method} {path} failed: {e}")
        return None


def _hubspot_find_contact_by_property(prop: str, value: str) -> Optional[str]:
    """Return an existing contact id whose `prop` exactly equals `value`, else None."""
    if not value:
        return None
    body = _hubspot_request("POST", "/crm/v3/objects/contacts/search", {
        "filterGroups": [
            {"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}
        ],
        "properties": [prop],
        "limit": 1,
    })
    results = (body or {}).get("results") or []
    return results[0].get("id") if results else None


def _hubspot_find_contact_by_phone(phone: str) -> Optional[str]:
    """Idempotency layer 2: existing contact id matching this phone."""
    return _hubspot_find_contact_by_property("phone", phone)


def _ig_fetch_username(igsid: str) -> Optional[str]:
    """
    Resolve an Instagram-scoped id (IGSID) to its @username via the Graph API
    (graph.instagram.com — the Instagram-login host). Best-effort: returns None
    on any error so a lookup failure never blocks lead capture or CRM sync.
    """
    if not (settings.ig_access_token and igsid):
        return None
    url = (f"https://graph.instagram.com/v21.0/{igsid}"
           f"?fields=username&access_token={settings.ig_access_token}")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
        return body.get("username") or None
    except Exception as e:
        logger.warning(f"[instagram] username fetch for {igsid} failed: {e}")
        return None


def _hubspot_upsert_contact(name: Optional[str], phone: str,
                            intent_summary: Optional[str],
                            channel: str = "telegram",
                            external_user_id: Optional[str] = None,
                            username: Optional[str] = None) -> Optional[str]:
    """
    Find-or-create a Contact. Dedup order: phone → instagram_psid → create.

    For Instagram leads we also stamp the custom instagram_psid / instagram_username
    properties, so the contact is identifiable and dedupable by IG identity even
    when the phone differs or was reformatted across channels. Returns contact id.
    """
    e164 = _crm_format_phone(phone)
    props: dict = {"phone": e164, "lifecyclestage": "lead", "hs_lead_status": "NEW"}
    if name:
        props["firstname"] = name
    if intent_summary and settings.hubspot_intent_property:
        props[settings.hubspot_intent_property] = intent_summary
    if channel == "instagram":
        if external_user_id:
            props["instagram_psid"] = external_user_id
        if username:
            props["instagram_username"] = username
            # Map the @username to firstname so the contact shows a name in the
            # HubSpot contacts directory instead of "--". Only applied when no
            # explicit name was captured (e.g. IG DMs never share a full name).
            if not name:
                props["firstname"] = username

    # Dedup: phone first, then Instagram-scoped id (catches the same person whose
    # phone differs / was reformatted, or who has no phone match yet).
    existing = _hubspot_find_contact_by_phone(e164)
    if not existing and channel == "instagram" and external_user_id:
        existing = _hubspot_find_contact_by_property("instagram_psid", external_user_id)

    if existing:
        body = _hubspot_request("PATCH", f"/crm/v3/objects/contacts/{existing}",
                                {"properties": props})
        contact_id = existing if body is not None else None
    else:
        body = _hubspot_request("POST", "/crm/v3/objects/contacts",
                                {"properties": props})
        contact_id = (body or {}).get("id")

    # No custom field configured → attach intent as a Note (best-effort).
    if contact_id and intent_summary and not settings.hubspot_intent_property:
        _hubspot_add_note(contact_id, intent_summary)
    return contact_id


def _hubspot_add_note(contact_id: str, intent_summary: str) -> None:
    """Attach the intent summary as a Note associated to the contact."""
    _hubspot_request("POST", "/crm/v3/objects/notes", {
        "properties": {
            "hs_note_body": intent_summary,
            "hs_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        "associations": [{
            "to":    {"id": contact_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED",
                       "associationTypeId": 202}],   # note → contact
        }],
    })


def _hubspot_resolve_stage() -> tuple:
    """
    Return (pipeline_id, stage_id). Uses the configured IDs when set, otherwise
    auto-discovers the default deal pipeline's first stage and caches it for the
    process lifetime. Returns (None, None) if discovery fails.
    """
    global _hubspot_pipeline_cache
    if settings.hubspot_pipeline_id and settings.hubspot_stage_id:
        return settings.hubspot_pipeline_id, settings.hubspot_stage_id
    if _hubspot_pipeline_cache is not None:
        return _hubspot_pipeline_cache

    body = _hubspot_request("GET", "/crm/v3/pipelines/deals")
    pipelines = (body or {}).get("results") or []
    if not pipelines:
        return None, None
    pipeline = next((p for p in pipelines if p.get("id") == "default"), None) \
        or min(pipelines, key=lambda p: p.get("displayOrder", 0))
    stages = pipeline.get("stages") or []
    if not stages:
        return None, None
    stage = min(stages, key=lambda s: s.get("displayOrder", 0))
    _hubspot_pipeline_cache = (pipeline.get("id"), stage.get("id"))
    logger.info(f"[crm] HubSpot pipeline auto-discovered: {_hubspot_pipeline_cache}")
    return _hubspot_pipeline_cache


_CRM_CHANNEL_LABEL = {"instagram": "אינסטגרם", "telegram": "טלגרם"}


def _hubspot_create_deal(contact_id: str, name: Optional[str],
                         channel: str = "telegram") -> None:
    """Create a Deal in the resolved pipeline/stage, associated to the contact."""
    pipeline_id, stage_id = _hubspot_resolve_stage()
    if not (pipeline_id and stage_id):
        logger.warning("[crm] No deal pipeline/stage resolved — contact synced "
                       "without a deal.")
        return
    label = _CRM_CHANNEL_LABEL.get(channel, channel)
    deal_name = f"ליד {label} — {name}" if name else f"ליד {label}"
    _hubspot_request("POST", "/crm/v3/objects/deals", {
        "properties": {
            "dealname":  deal_name,
            "pipeline":  pipeline_id,
            "dealstage": stage_id,
        },
        "associations": [{
            "to":    {"id": contact_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED",
                       "associationTypeId": 3}],      # deal → contact
        }],
    })


def _hubspot_sync_lead(name: Optional[str], phone: str,
                       intent_summary: Optional[str],
                       channel: str = "telegram",
                       external_user_id: Optional[str] = None,
                       username: Optional[str] = None) -> Optional[str]:
    """Upsert Contact (idempotent) + create associated Deal. Returns contact id."""
    # Resolve the @username for Instagram leads when not already provided — e.g.
    # the cron backstop path, which has no inline fetch.
    if channel == "instagram" and not username and external_user_id:
        username = _ig_fetch_username(external_user_id)
    contact_id = _hubspot_upsert_contact(name, phone, intent_summary, channel,
                                         external_user_id, username)
    if contact_id:
        _hubspot_create_deal(contact_id, name, channel)
        logger.info(f"[crm] HubSpot synced {channel} lead → contact {contact_id}")
    return contact_id


def _db_mark_lead_synced(conn, lead_id: str, external_id: str) -> None:
    """Stamp crm_external_id + crm_synced_at so the reconciler skips this lead."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE leads SET crm_external_id = %s, crm_synced_at = NOW() "
            "WHERE id = %s",
            (external_id, lead_id),
        )


def _finalize_lead(lead_id: str, name: Optional[str], phone: str,
                   intent_summary: Optional[str], chat_id: str,
                   channel: str = "telegram",
                   defer_owner_alert: bool = False) -> None:
    """
    Single post-save side-effect funnel for ALL capture paths:
    owner alert → CRM sync → stamp notified_at (+ crm_synced_at on success),
    in one commit. Entirely best-effort: any failure is logged, never raised —
    the caller has already sent the user's confirmation. Leads that fail the CRM
    push keep crm_synced_at = NULL and are retried by /api/cron/crm-sync.

    defer_owner_alert (Instagram alert unification): when True, the Telegram
    owner alert is NOT sent here — Erez receives exactly ONE combined message
    (lead details + 🧠 brief) at the awaiting_context turn instead (see
    _deliver_lead_brief). notified_at deliberately stays NULL so the exit-path
    flushes (_send_pending_ig_alert) and the cron backstop guarantee the alert
    is delayed, never lost. CRM sync is unaffected either way.
    """
    # Resolve the @username once for Instagram (used by BOTH the alert deep link
    # and the HubSpot record) so we never make the Graph API call twice.
    # FAIL-SAFE: the fetch is wrapped in its own try/except so that a Graph API
    # permission error, network timeout, or any other exception can NEVER block
    # the owner alert. If the lookup fails, username stays None and the alert
    # fires anyway with the IGSID as a fallback identifier.
    username = None
    if channel == "instagram":
        try:
            username = _ig_fetch_username(chat_id)
        except Exception as e:
            logger.warning(f"[leads] username fetch failed for {chat_id}: {e} — "
                           "alert will fire with IGSID fallback")

    alert_message_id = None
    if defer_owner_alert:
        logger.info(f"[leads] owner alert deferred for {lead_id} "
                    "(single combined alert at the context turn)")
    else:
        try:
            alert_message_id = _alert_owner(lead_id, name, phone, intent_summary,
                                            chat_id, channel=channel, username=username)
        except Exception as e:
            logger.error(f"[leads] owner alert failed for {lead_id}: {e}")

    external_id = None
    try:
        external_id = _crm_sync_lead(name, phone, intent_summary, channel=channel,
                                     external_user_id=chat_id, username=username)
    except Exception as e:
        logger.error(f"[crm] sync failed for lead {lead_id}: {e}")

    try:
        with get_db_conn() as conn:
            if not defer_owner_alert:
                _db_mark_lead_notified(conn, lead_id)
            if external_id:
                _db_mark_lead_synced(conn, lead_id, external_id)
            _db_set_lead_alert_message_id(conn, lead_id, alert_message_id)
            conn.commit()
    except Exception as e:
        logger.error(f"[leads] finalize bookkeeping failed for {lead_id}: {e}")

    # ── NEXUS Hook B — capture spine ──────────────────────────────────────────
    # person resolve → phone identity → leads/sessions person stamp →
    # opportunity 'captured' → interaction log. Own connection + commit inside;
    # NEVER raises (see nexus/hooks.py). Runs LAST so every legacy side-effect
    # above is fully untouched even if the spine write fails. Idempotent under
    # webhook replays (unique indexes + forward-only stages + dedup_key).
    nexus_hooks.on_lead_captured(lead_id, channel=channel, chat_id=chat_id,
                                 phone=phone)


# ── Lead Brief — post-capture conversation intelligence ───────────────────────
# Runs ONLY after a lead is captured and the user answers the optional topic
# question (the awaiting_context turn). It is grounded in the lead's own words,
# so it informs rather than hallucinates. Best-effort everywhere: a failure
# leaves the (already-complete) lead untouched.

_LEAD_BRIEF_PROMPT = """\
You are preparing Erez Gartsman — a relationship & dating coach — for a personal
WhatsApp conversation with a new lead. Using ONLY the lead's own words, write a
SHORT practical briefing in HEBREW so Erez can open the conversation prepared
and human.

Lead's own words:
\"\"\"{context}\"\"\"

{history_block}Return ONLY a strict JSON object, nothing else:
{{"topic": "<2-5 word Hebrew phrase>",
  "emotional_state": "<2-4 Hebrew words>",
  "urgency": <integer 1-5>,
  "opening": "<one warm, concrete Hebrew sentence Erez could open with>"}}

Rules:
- Ground every value in their words — never invent facts.
- urgency: 1 = casual/curious, 5 = acute distress / wants help now.
- "opening" must be gentle and human — NOT salesy, NOT clinical.
- No markdown, no commentary, nothing outside the JSON object.
"""


def _generate_lead_brief(context_text: str, history: list = None) -> Optional[dict]:
    """
    Turn the lead's one-line topic answer into a structured briefing dict, or None
    on any failure. Never raises. urgency is clamped to 1..5.
    """
    try:
        prompt = _LEAD_BRIEF_PROMPT.format(
            context=(context_text or "")[:1000],
            history_block=_build_rag_history_block(history or []),
        )
        parsed = _parse_llm_json(_call_llm(prompt))
        try:
            urgency = max(1, min(int(parsed.get("urgency")), 5))
        except (TypeError, ValueError):
            urgency = None
        return {
            "topic":           (parsed.get("topic") or "").strip()[:80] or None,
            "emotional_state": (parsed.get("emotional_state") or "").strip()[:60] or None,
            "urgency":         urgency,
            "opening":         (parsed.get("opening") or "").strip()[:300] or None,
        }
    except Exception as e:
        logger.warning(f"[brief] generation failed: {e}")
        return None


def _format_brief_message(brief: dict, context_text: str) -> str:
    """Telegram-formatted Lead Brief (the second message Erez gets, post-capture)."""
    urgency = brief.get("urgency")
    return "\n".join([
        "🧠 תקציר ליד",
        "",
        f"📌 נושא: {brief.get('topic') or '—'}",
        f"❤️ מצב: {brief.get('emotional_state') or '—'}",
        f"⚡ דחיפות: {urgency}/5" if urgency else "⚡ דחיפות: —",
        f"🗣️ פתיח מוצע: {brief.get('opening') or '—'}",
        "",
        f"במילים שלהם: \"{(context_text or '').strip()[:200]}\"",
    ])


def _deliver_lead_brief(igsid: str, context_text: str, history: list = None) -> None:
    """
    Instagram alert unification: on Instagram the capture-time owner alert is
    DEFERRED (_finalize_lead's defer_owner_alert), and THIS function sends
    Erez exactly ONE combined Telegram message — lead details + 🧠 brief —
    when the lead answers the optional topic question.

    Guarantees:
      • The alert is never lost to an LLM hiccup: when brief generation fails,
        the PLAIN alert (details only) is sent instead.
      • If the alert already went out (the cron backstop won the race, or a
        pre-unification lead), the brief is appended by editing that message
        in place — a standalone brief message only as a last resort.
      • HubSpot leg unchanged: the brief is attached as a Note when synced.
    Best-effort throughout; never raises into the webhook turn.
    """
    brief = _generate_lead_brief(context_text, history)   # None on any failure

    lead_id = phone = alert_message_id = contact_id = notified_at = None
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, phone, alert_message_id, crm_external_id, notified_at "
                    "FROM leads WHERE channel = 'instagram' AND chat_id = %s "
                    "ORDER BY created_at DESC LIMIT 1",
                    (igsid,),
                )
                row = cur.fetchone()
        if row:
            lead_id, phone, alert_message_id, contact_id, notified_at = (
                str(row[0]), row[1], row[2], row[3], row[4])
    except Exception as e:
        logger.warning(f"[brief] lead lookup failed: {e}")
    if not lead_id:
        return   # no captured lead behind this context turn — nothing to send

    if settings.telegram_owner_chat_id:
        try:
            username = _ig_fetch_username(igsid)
        except Exception:
            username = None
        # brief=None renders the plain details-only alert — same formatter,
        # one source of truth for the message shape.
        full_text = _format_lead_alert(
            name=None, phone=phone or "—", intent_summary=None, chat_id=igsid,
            channel="instagram", username=username, brief=brief)

        if notified_at:
            # Already alerted (backstop race / pre-unification lead) → enrich
            # only; NEVER re-send the details as a fresh message.
            if brief:
                edited = bool(alert_message_id) and _edit_telegram_message(
                    settings.telegram_owner_chat_id, alert_message_id, full_text)
                if not edited:
                    try:
                        _send_telegram_message(
                            settings.telegram_owner_chat_id,
                            _format_brief_message(brief, context_text))
                    except Exception as e:
                        logger.warning(f"[brief] standalone brief send failed: {e}")
        else:
            # THE single combined send (details + brief, or plain on LLM miss).
            message_id = _send_telegram_message(settings.telegram_owner_chat_id,
                                                full_text)
            try:
                with get_db_conn() as conn:
                    _db_mark_lead_notified(conn, lead_id)
                    _db_set_lead_alert_message_id(conn, lead_id, message_id)
                    conn.commit()
            except Exception as e:
                logger.error(f"[leads] combined-alert bookkeeping failed "
                             f"for {lead_id}: {e}")

    # HubSpot note — only when there is an actual brief and a synced contact.
    if brief and contact_id:
        try:
            _hubspot_add_note(contact_id, _format_brief_message(brief, context_text))
        except Exception as e:
            logger.warning(f"[brief] HubSpot note failed: {e}")
    elif brief:
        logger.info("[brief] contact not yet synced — HubSpot note deferred "
                    "(cron will sync the lead; Telegram alert already delivered).")


def _send_pending_ig_alert(igsid: str) -> None:
    """
    Flush a DEFERRED Instagram owner alert WITHOUT a brief — used when the
    awaiting_context window closes without a usable topic answer (escape,
    crisis, sub-4-char reply, or the lead resurfacing later via the cold
    gate). Idempotent via notified_at: no unnotified lead → silent no-op.
    Best-effort: never raises into the webhook turn. Leads who never send
    another message at all are caught by the cron backstop instead.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, phone FROM leads "
                    "WHERE channel = 'instagram' AND chat_id = %s "
                    "AND notified_at IS NULL "
                    "ORDER BY created_at DESC LIMIT 1",
                    (igsid,),
                )
                row = cur.fetchone()
        if not row:
            return
        lead_id, phone = str(row[0]), row[1]
        username = None
        try:
            username = _ig_fetch_username(igsid)
        except Exception:
            pass
        message_id = _alert_owner(lead_id, None, phone, None, igsid,
                                  channel="instagram", username=username)
        with get_db_conn() as conn:
            _db_mark_lead_notified(conn, lead_id)
            _db_set_lead_alert_message_id(conn, lead_id, message_id)
            conn.commit()
    except Exception as e:
        logger.error(f"[leads] pending IG alert flush failed for {igsid}: {e}")


# Bot-authored system messages are Hebrew to match the representative persona.
# The /start greeting and the crisis response are config-driven (app_config,
# editable live in Supabase); the short operational notices below stay in code.
_TG_NON_TEXT   = "אני יודע לקרוא רק הודעות טקסט כרגע 🙂 כתבו לי שאלה ואשמח לעזור."
_TG_TOO_LONG   = "ההודעה קצת ארוכה מדי. נסו לנסח אותה בקצרה ואענה."
_TG_MODERATION = "לא הצלחתי לעבד את ההודעה. נסו לשאול על השירותים, על ארז, או על קביעת פגישה."
_TG_RATE_LIMIT = "קצת הרבה הודעות בבת אחת 🙂 נסו שוב בעוד רגע."
_TG_TIMEOUT    = "סליחה, לקח לי קצת יותר מדי זמן לחשוב. נסו לשאול שוב."
_TG_ERROR      = "משהו השתבש אצלי כרגע. נסו שוב בעוד רגע."


def _db_get_or_create_telegram_session(conn, chat_id: str) -> str:
    """Thin shim — delegates to the channel-generic helper."""
    return _db_get_or_create_channel_session(conn, "telegram", chat_id)


def _send_telegram_message(chat_id, text: str, reply_markup: dict = None):
    """
    Deliver a reply via Telegram's sendMessage. Uses the stdlib urllib so no HTTP
    dependency is added to the serverless bundle. Best-effort: any network error
    is logged, never raised — the webhook must always return 200 or Telegram will
    retry the update and the user gets duplicate replies.

    Returns the sent message_id (int) on success, or None — callers that want to
    later edit the message (e.g. the lead alert) persist this id; all other
    callers simply ignore the return value.

    reply_markup: optional Telegram ReplyKeyboardMarkup / ReplyKeyboardRemove dict.
    """
    if not settings.telegram_bot_token:
        logger.error("[telegram] TELEGRAM_BOT_TOKEN not set — cannot send reply.")
        return None

    text    = (text or "").strip()[:4096] or "…"   # Telegram hard-caps at 4096 chars
    url     = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
        return (body.get("result") or {}).get("message_id")
    except Exception as e:
        logger.error(f"[telegram] sendMessage to {chat_id} failed: {e}")
        return None


def _edit_telegram_message(chat_id, message_id, text: str) -> bool:
    """
    Replace the text of an already-sent Telegram message via editMessageText.
    Used to fold the Lead Brief INTO the original capture alert (one evolving
    message instead of two). Best-effort: returns True on success, False on any
    failure (caller falls back to sending a new message).
    """
    if not (settings.telegram_bot_token and message_id):
        return False
    text = (text or "").strip()[:4096] or "…"
    url  = f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageText"
    data = json.dumps({"chat_id": chat_id, "message_id": message_id,
                       "text": text}).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        logger.warning(f"[telegram] editMessageText {message_id} failed: {e}")
        return False


def _send_contact_keyboard(chat_id, preamble: str) -> None:
    """
    Send the contact-share keyboard with `_TG_CONTACT_PROMPT` always appended.

    The prompt explains how to find the contact button when Telegram's standard
    keyboard pops up and hides it — a UX trap that is otherwise invisible to the
    user. Centralising keyboard delivery here ensures the instructions can never
    be accidentally omitted from any code path that shows the keyboard.
    """
    _send_telegram_message(
        chat_id,
        f"{preamble}\n\n{_TG_CONTACT_PROMPT}{_config_suffix('consent.capture_line')}",
        reply_markup=_CONTACT_KEYBOARD,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MessagingChannel — channel adapter seam (Sprint 2.1)
#
# Why this exists:
#   The funnel core (state machine, triage LLM, lead upsert, HubSpot sync) is
#   already channel-agnostic. The only channel-specific surface is *sending*:
#   Telegram has reply-keyboards and contact-share buttons; Instagram has
#   quick-replies and URL-button templates. This seam lets the shared funnel
#   code call self.channel.send_text(...) without knowing which wire it's on.
#
# Extending: implement MessagingChannel, instantiate in the webhook handler,
#   and pass it down. No changes needed in the shared funnel logic.
# ─────────────────────────────────────────────────────────────────────────────

class MessagingChannel:
    """Abstract base — one concrete subclass per messaging platform."""

    CHANNEL_NAME: str = ""   # "telegram" | "instagram"

    def send_text(self, recipient_id: str, text: str) -> None:
        raise NotImplementedError

    def send_quick_replies(self, recipient_id: str, text: str,
                           replies: list[dict]) -> None:
        """
        Send text with 1-13 ephemeral quick-reply chips.
        Each reply: {"title": str (≤20 chars on IG), "payload": str}
        """
        raise NotImplementedError

    def send_buttons(self, recipient_id: str, text: str,
                     buttons: list[dict]) -> None:
        """
        Send a persistent button template.
        Each button: {"type": "web_url"|"postback", "title": str,
                      "url": str (web_url only), "payload": str (postback only)}
        """
        raise NotImplementedError

    def send_contact_prompt(self, recipient_id: str, preamble: str) -> None:
        """Channel-specific CTA to collect contact info (keyboard / URL buttons)."""
        raise NotImplementedError

    def send_lead_thanks(self, recipient_id: str, name: str | None) -> None:
        """Confirmation sent immediately after lead capture."""
        self.send_text(recipient_id, _format_lead_thanks(name))

    def dismiss_keyboard(self, recipient_id: str) -> None:
        """Remove any persistent keyboard / quick-reply row (no-op where N/A)."""
        pass  # default: no-op (Instagram quick-replies are ephemeral)

    def mark_seen(self, recipient_id: str) -> None:
        """Send a read-receipt / typing indicator (best-effort, never raises)."""
        pass  # default: no-op


# ── Telegram implementation ───────────────────────────────────────────────────

class TelegramChannel(MessagingChannel):
    """
    Wraps the existing _send_telegram_message / _send_contact_keyboard helpers.
    No behaviour change — this is a pure refactor that puts the seam in place.
    """

    CHANNEL_NAME = "telegram"

    def send_text(self, recipient_id: str, text: str,
                  reply_markup: dict = None) -> None:
        _send_telegram_message(recipient_id, text, reply_markup)

    def send_quick_replies(self, recipient_id: str, text: str,
                           replies: list[dict]) -> None:
        # Telegram maps quick-replies to a one-time ReplyKeyboard.
        keyboard = [[{"text": r["title"]}] for r in replies]
        _send_telegram_message(recipient_id, text, reply_markup={
            "keyboard":          keyboard,
            "resize_keyboard":   True,
            "one_time_keyboard": True,
        })

    def send_buttons(self, recipient_id: str, text: str,
                     buttons: list[dict]) -> None:
        # Telegram has no native URL button template — send as inline keyboard.
        rows = []
        for b in buttons:
            if b.get("type") == "web_url":
                rows.append([{"text": b["title"], "url": b["url"]}])
            else:
                rows.append([{"text": b["title"],
                              "callback_data": b.get("payload", b["title"])}])
        _send_telegram_message(recipient_id, text, reply_markup={
            "inline_keyboard": rows,
        })

    def send_contact_prompt(self, recipient_id: str, preamble: str) -> None:
        _send_contact_keyboard(recipient_id, preamble)

    def send_lead_thanks(self, recipient_id: str, name: str | None) -> None:
        _send_telegram_message(recipient_id, _format_lead_thanks(name),
                               reply_markup=_REMOVE_KEYBOARD)

    def dismiss_keyboard(self, recipient_id: str) -> None:
        # Pass _REMOVE_KEYBOARD as part of the next message instead of a
        # standalone send (Telegram requires text alongside reply_markup).
        pass  # callers already pass reply_markup=_REMOVE_KEYBOARD explicitly


# ── Instagram implementation ──────────────────────────────────────────────────

# IG contact-prompt copy (no share-contact keyboard on Instagram).
_IG_CONTACT_PROMPT = (
    "כדי שארז יוכל לחזור אליכם, בחרו את הדרך הנוחה לכם:"
)

# Fallback when no WhatsApp/Calendly is configured — ask for typed phone.
_IG_CONTACT_PROMPT_FALLBACK = (
    "כדי שארז יוכל לחזור אליכם, הקלידו את מספר הטלפון שלכם כאן:"
)

# Generic error message mirroring the Telegram set.
_IG_NON_TEXT   = "אני יודע לקרוא רק הודעות טקסט כרגע 🙂 כתבו לי שאלה ואשמח לעזור."
_IG_TOO_LONG   = "ההודעה קצת ארוכה מדי. נסו לנסח אותה בקצרה ואענה."
_IG_MODERATION = "לא הצלחתי לעבד את ההודעה. נסו לשאול על השירותים, על ארז, או על קביעת פגישה."
_IG_RATE_LIMIT = "קצת הרבה הודעות בבת אחת 🙂 נסו שוב בעוד רגע."
_IG_TIMEOUT    = "סליחה, לקח לי קצת יותר מדי זמן לחשוב. נסו לשאול שוב."
_IG_ERROR      = "משהו השתבש אצלי כרגע. נסו שוב בעוד רגע."

# ── Icebreaker flow copy (first person — Erez operates solo, there is no "team") ─
# Exact warm reply sent the moment the configured Icebreaker is tapped. It asks
# directly for the prospect's WhatsApp number; their next message is captured as
# the lead (the handler jumps straight to awaiting_contact, no qualification step).
_IG_ICEBREAKER_REPLY = (
    "היי, איזה כיף שפנית! אשמח לתת לך את כל הפרטים. מה מספר הווטסאפ שלך? "
    "אשלח לך לשם הודעה בהקדם ונראה יחד איך אפשר לעזור. 🙂"
)
# Gentle re-ask when the user is in awaiting_contact but didn't send a number.
_IG_CONTACT_RETRY = (
    "אשמח למספר הווטסאפ שלך כדי שאשלח לך הודעה ונתקדם משם 🙂"
)
# First-person confirmation once the number is captured.
_IG_LEAD_THANKS = (
    "תודה רבה! 🙏 קיבלתי, ואשלח לך הודעה בווטסאפ בהקדם. מחכה לדבר! 🙂"
)
# Capture-confirmation that ALSO asks one optional topic question, so we can
# build a Lead Brief. The lead is ALREADY captured at this point — answering is
# pure upside and cannot affect the conversion rate ("capture first, enrich
# second"). The "אם בא לך" framing keeps it pressure-free.
_IG_LEAD_THANKS_CONTEXT = (
    "תודה רבה! 🙏 קיבלתי ואשלח לך הודעה בווטסאפ בהקדם. "
    "אם בא לך — ספרו לי במשפט אחד על מה תרצו שנדבר, וזה יעזור לי להגיע מוכן 🙂"
)
# Warm close after the user shares (or skips) their topic line.
_IG_CONTEXT_ACK = (
    "מעולה, תודה ששיתפתם 🙏 אדבר איתכם בקרוב בווטסאפ."
)
# First-person ack for a returning lead who taps the Icebreaker again.
_IG_ALREADY_LEAD_REPLY = (
    "הפרטים שלך כבר אצלי 🙏 אחזור אליך בהקדם בווטסאפ. 🙂"
)


def _ig_graph_call(path: str, payload: dict) -> None:
    """
    POST to the Instagram Graph API send endpoint (/me/messages).
    Uses stdlib urllib — no extra dependency.
    Best-effort: logs on failure, never raises (webhook must always return 200).

    HOST: the "Instagram API with Instagram Login" flow (no Facebook Page) is
    served by graph.instagram.com — NOT graph.facebook.com. Using the wrong host
    returns an OAuth/permission error and the reply silently fails.
    """
    if not settings.ig_access_token:
        logger.error("[instagram] IG_ACCESS_TOKEN not set — cannot send reply.")
        return
    url  = f"https://graph.instagram.com/v21.0/me/messages?access_token={settings.ig_access_token}"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        logger.error(f"[instagram] Graph API call to {path} failed: {e}")


class InstagramChannel(MessagingChannel):
    """
    Instagram Messaging via the Meta Graph API v21.0 / Messenger Send API.

    Quick-replies: ephemeral chips (≤13, title ≤20 chars) for yes/no funnel.
    Button templates: persistent URL buttons for WhatsApp/Calendly CTAs.
    Typed phone: always accepted via _extract_phone_from_text — no API surface.

    CTA: a single WhatsApp wa.me button built from WHATSAPP_NUMBER env var.
    Falls back to asking the user to type their number when the var is unset.
    """

    CHANNEL_NAME = "instagram"

    def _recipient(self, igsid: str) -> dict:
        return {"id": igsid}

    def send_text(self, recipient_id: str, text: str) -> None:
        text = (text or "").strip()[:1000] or "…"   # IG hard cap is 1000 chars
        _ig_graph_call("/me/messages", {
            "recipient":      self._recipient(recipient_id),
            "message":        {"text": text},
            "messaging_type": "RESPONSE",
        })

    def send_quick_replies(self, recipient_id: str, text: str,
                           replies: list[dict]) -> None:
        qr = [
            {"content_type": "text",
             "title":        r["title"][:20],   # IG enforces 20-char max
             "payload":      r.get("payload", r["title"])}
            for r in replies[:13]               # IG enforces max 13
        ]
        _ig_graph_call("/me/messages", {
            "recipient":      self._recipient(recipient_id),
            "message":        {"text": (text or "").strip()[:1000],
                               "quick_replies": qr},
            "messaging_type": "RESPONSE",
        })

    def send_buttons(self, recipient_id: str, text: str,
                     buttons: list[dict]) -> None:
        elements = [{
            "title":   (text or "")[:80],   # generic template title max 80 chars
            "buttons": [
                ({"type": "web_url", "url": b["url"], "title": b["title"][:20]}
                 if b.get("type") == "web_url"
                 else {"type": "postback", "title": b["title"][:20],
                       "payload": b.get("payload", b["title"])})
                for b in buttons[:3]         # IG generic template max 3 buttons
            ],
        }]
        _ig_graph_call("/me/messages", {
            "recipient":      self._recipient(recipient_id),
            "message":        {
                "attachment": {
                    "type":    "template",
                    "payload": {"template_type": "generic", "elements": elements},
                }
            },
            "messaging_type": "RESPONSE",
        })

    def send_contact_prompt(self, recipient_id: str, preamble: str) -> None:
        buttons = self._contact_buttons(recipient_id)
        consent = _config_suffix("consent.capture_line")
        if buttons:
            # Send the preamble (+ consent) as plain text, then the button template.
            self.send_text(recipient_id, f"{preamble}{consent}")
            self.send_buttons(recipient_id, _IG_CONTACT_PROMPT, buttons)
        else:
            # No env vars configured — fall back to asking for typed phone.
            self.send_text(recipient_id,
                           f"{preamble}\n\n{_IG_CONTACT_PROMPT_FALLBACK}{consent}")

    def send_lead_thanks(self, recipient_id: str, name: str | None = None) -> None:
        # First-person confirmation (no "team"); overrides the base/Telegram copy.
        self.send_text(recipient_id, _IG_LEAD_THANKS)

    def mark_seen(self, recipient_id: str) -> None:
        _ig_graph_call("/me/messages", {
            "recipient":     self._recipient(recipient_id),
            "sender_action": "mark_seen",
        })

    def _contact_buttons(self, recipient_id: str) -> list[dict]:
        """
        Returns a single WhatsApp wa.me button when WHATSAPP_NUMBER is set,
        or an empty list (triggers typed-phone fallback) when it is not.

        NEXUS Hook D: the URL carries a per-person ref-code prefill so the
        WhatsApp arrival can be linked back to this Instagram person in the
        cockpit. whatsapp_cta_url() HARD-GUARANTEES a usable link — any
        failure (DB down, no person, encoding error, malformed/oversized
        result) returns the plain wa.me/<number> the bot has always sent.
        The conversion CTA can be upgraded by nexus, never broken by it.
        """
        if settings.whatsapp_number:
            return [{
                "type":  "web_url",
                "title": "המשך בוואטסאפ",
                "url":   nexus_hooks.whatsapp_cta_url(
                    settings.whatsapp_number, "instagram", recipient_id),
            }]
        return []


# ── Shared channel registry ───────────────────────────────────────────────────

_TELEGRAM_CHANNEL  = TelegramChannel()
_INSTAGRAM_CHANNEL = InstagramChannel()


def _tg_clear_state(chat_id_str: str) -> None:
    """
    Best-effort: clear any funnel bot_state for this chat. Used by the explicit
    exit commands (/start, /cancel) and the crisis handler. Never raises — a DB
    hiccup must not block the user-facing reply that accompanies the reset.
    """
    try:
        with get_db_conn() as conn:
            sid = _db_get_or_create_telegram_session(conn, chat_id_str)
            if _db_get_session_state(conn, sid):   # only write when there's state to clear
                _db_set_session_state(conn, sid, None)
                conn.commit()
    except Exception:
        pass


@app.post("/api/webhook/telegram")
def telegram_webhook(
    update: dict = Body(default={}),
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
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
    if settings.telegram_webhook_secret:
        if not _secret_eq(x_telegram_bot_api_secret_token, settings.telegram_webhook_secret):
            logger.warning("[telegram] Rejected webhook: bad/missing secret token.")
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
                with get_db_conn() as conn:
                    session_id     = _db_get_or_create_telegram_session(conn, chat_id_str)
                    history        = _db_load_history(conn, session_id, limit=12)
                    intent_summary = _build_intent_summary(history, "")
                    lead_id        = _db_save_lead(
                        conn, session_id, chat_id_str, name, phone, intent_summary
                    )
                    conn.commit()

                # Warm confirmation FIRST so the user gets instant feedback —
                # the slow owner-alert + CRM sync must never delay it (P1).
                _send_telegram_message(chat_id, _format_lead_thanks(name),
                                       reply_markup=_REMOVE_KEYBOARD)
                if lead_id:
                    # Owner alert + CRM sync + bookkeeping (best-effort, post-ack).
                    _finalize_lead(lead_id, name, phone, intent_summary, chat_id_str)
                    _audit("lead_captured", chat_id=chat_id_str,
                           lead_id=lead_id, phone_len=len(phone))
                else:
                    logger.info(f"[leads] Duplicate contact from {chat_id_str} — skipped.")
            except Exception as e:
                logger.error(f"[leads] Contact capture failed: {e}", exc_info=True)
                _send_telegram_message(chat_id, _TG_ERROR,
                                       reply_markup=_REMOVE_KEYBOARD)
        return {"ok": True}

    # ── 2b. Parse text ────────────────────────────────────────────────────────
    # Fall back to a photo/document caption so a user who types their question in
    # an image caption is understood instead of being told "text only".
    text = (message.get("text") or message.get("caption") or "").strip()

    if not text:
        _send_telegram_message(chat_id, _TG_NON_TEXT)   # sticker / voice / image w/o caption
        return {"ok": True}
    # ── Explicit commands are the ONLY way to exit a funnel state ─────────────
    # In a funnel (e.g. awaiting_qualification) free text is always treated as
    # the user's answer — never as a cancellation — so the deliberate /start and
    # /cancel commands are the sole, unambiguous escape hatch. Both reset state.
    if text.startswith("/start"):
        _tg_clear_state(chat_id_str)
        _send_telegram_message(
            chat_id,
            _get_config("telegram.greeting") + _config_suffix("disclosure.line"))
        return {"ok": True}
    if text.startswith("/cancel"):
        _tg_clear_state(chat_id_str)
        _send_telegram_message(chat_id, _TG_ESCAPE_RESPONSE)
        _audit("telegram_cancel_command", chat_id=chat_id_str)
        return {"ok": True}

    # ── Crisis check — always first among text handlers ───────────────────────
    # The empathetic response is delivered BEFORE any DB work so that a DB
    # hiccup can never block it. State is then cleared so the user returns to
    # a clean conversation after speaking with a professional — not the contact
    # keyboard or the qualification question.
    if is_crisis(text):
        _audit("telegram_crisis", chat_id=chat_id_str)
        _send_telegram_message(chat_id, _get_config("crisis.message"))
        _tg_clear_state(chat_id_str)   # best-effort; never blocks the crisis reply
        return {"ok": True}

    _audit("telegram_request", chat_id=chat_id_str, question=_redact_text(text))

    # ── 3. Rate limit (in-memory — runs before DB checkout) ───────────────────
    try:
        check_rate_limit(chat_id_str)
    except RateLimitError:
        _send_telegram_message(chat_id, _TG_RATE_LIMIT)
        return {"ok": True}

    # ── 4. Identity mapping — before validate_question so bot_state can
    #       bypass the length guard for short replies like "כן" (2 chars). ─────
    try:
        with get_db_conn() as conn:
            session_id   = _db_get_or_create_telegram_session(conn, chat_id_str)
            bot_state    = _db_get_session_state(conn, session_id)
            already_lead = _db_has_lead(conn, chat_id_str)
            history      = _db_load_history(conn, session_id, limit=12)
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
                with get_db_conn() as conn:
                    _db_save_message(conn, session_id, "user", text)
                    _db_set_session_state(conn, session_id, _make_contact_state(0))
                    _db_touch_session(conn, session_id)
                    conn.commit()
                _send_contact_keyboard(chat_id, _TG_QUALIFICATION_ACK)
                _audit("telegram_qualification_answered", chat_id=chat_id_str,
                       session_id=session_id)
                # NEXUS C2 — best-effort, never raises (see nexus/hooks.py).
                nexus_hooks.on_funnel_event(
                    "qualified", "telegram", session_id=session_id,
                    stage="qualified", dedup_key=f"qualified:{session_id}")
                return {"ok": True}
            # Already a lead — nothing to capture; clear stale state and continue
            # to normal conversation below.
            with get_db_conn() as conn:
                _db_set_session_state(conn, session_id, None)
                conn.commit()
            bot_state = None

        # ── STATE: offered_meeting — interpret the reply to our consultation offer ─
        # The bot offered a meeting last turn. We classify the reply IN CONTEXT
        # (LLM-driven, natural-language-robust — see _bot_classify_offer_response)
        # and the STATE MACHINE acts: this is what makes a casual "אשמח" reliably
        # enter the funnel instead of the LLM hallucinating a closure. Handled
        # before the escape gate / moderation so a raw reply is never mishandled.
        if _is_offered_meeting(bot_state):
            if already_lead:
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
                bot_state = None   # already captured — fall through to normal chat
            else:
                decision, offer_reply = _bot_classify_offer_response(text, history)

                if decision == "AFFIRM":
                    # Code (not the LLM) opens the funnel: show the contact keyboard.
                    with get_db_conn() as conn:
                        _db_save_message(conn, session_id, "user", text)
                        _db_set_session_state(conn, session_id, _make_contact_state(0))
                        _db_touch_session(conn, session_id)
                        conn.commit()
                    _send_contact_keyboard(chat_id, _TG_OFFER_ACK)
                    _audit("telegram_offer_accepted", chat_id=chat_id_str,
                           session_id=session_id)
                    # NEXUS C3 — best-effort, never raises.
                    nexus_hooks.on_funnel_event(
                        "qualified", "telegram", session_id=session_id,
                        stage="qualified", dedup_key=f"qualified:{session_id}")
                    return {"ok": True}

                if decision == "DECLINE":
                    with get_db_conn() as conn:
                        _db_save_message(conn, session_id, "user", text)
                        _db_set_session_state(conn, session_id, None)
                        _db_touch_session(conn, session_id)
                        conn.commit()
                    _send_telegram_message(chat_id, _TG_OFFER_DECLINED)
                    _audit("telegram_offer_declined", chat_id=chat_id_str,
                           session_id=session_id)
                    return {"ok": True}

                # OTHER (question / hesitation / more sharing): warm reply + ONE
                # more soft offer, until the re-offer cap — then back off so we
                # never nag.
                count = _parse_offer_count(bot_state)
                with get_db_conn() as conn:
                    _db_save_message(conn, session_id, "user", text)
                    if count + 1 < _MAX_REOFFERS:
                        out = (f"{offer_reply}\n\n{_TG_MEETING_CTA}".strip()
                               if offer_reply else _TG_MEETING_CTA)
                        _db_set_session_state(conn, session_id,
                                              _make_offer_state(count + 1))
                    else:
                        out = offer_reply or _TG_OFFER_BACKOFF
                        _db_set_session_state(conn, session_id, None)
                    _db_save_message(conn, session_id, "assistant", out)
                    _db_touch_session(conn, session_id)
                    conn.commit()
                _send_telegram_message(chat_id, out)
                _audit("telegram_offer_other", chat_id=chat_id_str,
                       session_id=session_id, reoffers=count + 1)
                return {"ok": True}

        # ── Escape-intent gate (short opt-outs only; awaiting_contact etc.) ────
        # A SHORT opt-out ("לא", "בטל", "stop") while still in a funnel state
        # clears it gracefully. awaiting_qualification is already handled above,
        # so this primarily serves awaiting_contact. The word-count guard inside
        # _is_escape_intent guarantees a long emotional message is never treated
        # as an opt-out here either. Checked before validate_question so a 2-char
        # "לא" isn't rejected by the length guard first.
        if bot_state and _is_escape_intent(text):
            with get_db_conn() as conn:
                _db_set_session_state(conn, session_id, None)
                conn.commit()
            _send_telegram_message(chat_id, _TG_ESCAPE_RESPONSE)
            _audit("telegram_escape", chat_id=chat_id_str, prior_state=bot_state)
            return {"ok": True}

        # ── STATE: awaiting_contact ────────────────────────────────────────────
        # The contact keyboard was shown.  User must EITHER tap the native button
        # (handled as message.contact above) OR type their phone number.
        # Non-phone text gets a re-show with a retry counter; after
        # _MAX_CONTACT_RETRIES it exits gracefully.
        # Runs BEFORE validate_question so short replies ("כן", 2 chars) bypass
        # the length guard without producing a confusing error.
        if _is_awaiting_contact(bot_state):
            phone = _extract_phone_from_text(text)
            retry = _parse_contact_retry(bot_state)

            if already_lead:
                # Lead captured since the keyboard was shown — clear stale state.
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
                bot_state = None   # fall through to normal conversation
            elif phone:
                try:
                    intent_summary = _build_intent_summary(history, text)
                    with get_db_conn() as conn:
                        lead_id = _db_save_lead(conn, session_id, chat_id_str,
                                                None, phone, intent_summary)
                        _db_set_session_state(conn, session_id, None)
                        conn.commit()
                    if lead_id:
                        # Confirm first (instant ack), then sync (P1).
                        _send_telegram_message(chat_id, _format_lead_thanks(None),
                                               reply_markup=_REMOVE_KEYBOARD)
                        _finalize_lead(lead_id, None, phone, intent_summary, chat_id_str)
                        _audit("lead_captured_regex_awaiting", chat_id=chat_id_str,
                               lead_id=lead_id)
                except Exception as e:
                    logger.error(f"[leads] awaiting_contact capture: {e}", exc_info=True)
                    _send_telegram_message(chat_id, _TG_ERROR, reply_markup=_REMOVE_KEYBOARD)
                return {"ok": True}
            elif retry >= _MAX_CONTACT_RETRIES:
                # Graceful exit after three non-phone, non-escape replies.
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
                _send_telegram_message(chat_id, _TG_CONTACT_RETRY_EXHAUSTED,
                                       reply_markup=_REMOVE_KEYBOARD)
                _audit("telegram_contact_exhausted", chat_id=chat_id_str)
                return {"ok": True}
            else:
                # Non-phone, non-escape — increment counter, re-show keyboard.
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id,
                                          _make_contact_state(retry + 1))
                    conn.commit()
                _send_contact_keyboard(chat_id, _TG_AWAITING_CONTACT_RETRY)
                return {"ok": True}

        # ── 5. Content guards (only reached when not in a state machine branch) ─
        # Generous cap: this audience sends long, heartfelt messages. The funnel
        # states (handled above) have NO length limit at all; this only bounds
        # free-form RAG chat to keep the LLM token cost sane while still letting a
        # full emotional paragraph through (Telegram's own hard limit is 4096).
        if len(text) > 1500:
            _send_telegram_message(chat_id, _TG_TOO_LONG)
            return {"ok": True}
        try:
            validate_question(text)
        except InputModerationError:
            _audit("telegram_moderation_block", chat_id=chat_id_str)
            _send_telegram_message(chat_id, _TG_MODERATION)
            return {"ok": True}

        # (awaiting_qualification is handled earlier — before the escape gate and
        # moderation — so a raw emotional story is captured, never rejected.)

        # ── Regex phone fallback for normal conversation ───────────────────────
        phone_in_text = _extract_phone_from_text(text)
        if phone_in_text and not already_lead:
            try:
                intent_summary = _build_intent_summary(history, text)
                with get_db_conn() as conn:
                    lead_id = _db_save_lead(conn, session_id, chat_id_str,
                                            None, phone_in_text, intent_summary)
                    conn.commit()
                if lead_id:
                    # Confirm first (instant ack), then sync (P1).
                    _send_telegram_message(chat_id, _format_lead_thanks(None))
                    _finalize_lead(lead_id, None, phone_in_text, intent_summary, chat_id_str)
                    _audit("lead_captured_regex", chat_id=chat_id_str, lead_id=lead_id)
                    return {"ok": True}
            except Exception as e:
                logger.error(f"[leads] Regex capture failed: {e}", exc_info=True)

        # ── SAFETY NET: agreement to an offer whose state was lost ─────────────
        # Normally an offer arms 'offered_meeting', so the agreement turn is
        # handled above. But the state can be lost — most commonly when the 24h
        # bot_state TTL expires before the user replies. If we are NOT in a funnel
        # state yet the user clearly affirms AND our last message was an offer,
        # honour it and open the contact keyboard. This makes "אשמח" foolproof
        # regardless of how (or how long after) the conversation flowed.
        if (bot_state is None and not already_lead
                and _is_affirmation(text) and _last_bot_message_offered(history)):
            with get_db_conn() as conn:
                _db_save_message(conn, session_id, "user", text)
                _db_set_session_state(conn, session_id, _make_contact_state(0))
                _db_touch_session(conn, session_id)
                conn.commit()
            _send_contact_keyboard(chat_id, _TG_OFFER_ACK)
            _audit("telegram_offer_accepted_recovered", chat_id=chat_id_str,
                   session_id=session_id)
            # NEXUS C3 (state-loss recovery path) — best-effort, never raises.
            nexus_hooks.on_funnel_event(
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
        if bot_state is None and _has_booking_intent(text):
            if already_lead:
                reply_text  = _TG_ALREADY_LEAD_BOOKING
                new_state   = None
                audit_event = "telegram_already_lead_booking"
            else:
                reply_text  = _TG_QUALIFICATION_QUESTION
                new_state   = "awaiting_qualification"
                audit_event = "telegram_qualification_triggered"

            with get_db_conn() as conn:
                _db_save_message(conn, session_id, "user", text)
                _db_save_message(conn, session_id, "assistant", reply_text)
                if new_state:
                    _db_set_session_state(conn, session_id, new_state)
                _db_touch_session(conn, session_id)
                conn.commit()

            _send_telegram_message(chat_id, reply_text)
            _audit(audit_event, chat_id=chat_id_str, session_id=session_id)
            # NEXUS C4 — funnel entry on Telegram. Opens (or re-opens after a
            # closed episode) the opportunity at 'engaged'. Best-effort.
            nexus_hooks.on_funnel_event(
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
        query_vector = _embed_text(text)
        recall_block = ""
        with get_db_conn() as conn:
            chunks = _retrieve_chunks(conn, query_vector, top_k=5)
            # NEXUS Hook F — memory recall (3.5 Phase 2). Gated by the live
            # memory.recall_enabled flag; build_recall_block is read-only and
            # returns "" on any failure, so the prompt is unchanged when off,
            # for unknown persons, or on a recall hiccup.
            if _memory_recall_on():
                recall_block = nexus_memory.build_recall_block(
                    conn, session_id=session_id)

        reply, intent, sources = _bot_triage_reply(text, chunks, history=history,
                                                   recall_block=recall_block)

        # Offer is the default for anything SUBSTANTIVE (EMOTIONAL or FAQ) — only
        # SMALLTALK stays out of the funnel — and only for a NEW lead (an existing
        # lead just gets the brief reply; Erez already has their details).
        make_offer = (intent in ("EMOTIONAL", "FAQ") and not already_lead)
        out = f"{reply}\n\n{_TG_MEETING_CTA}" if make_offer else reply

        with get_db_conn() as conn:
            _db_save_message(conn, session_id, "user", text)
            _db_save_message(conn, session_id, "assistant", out)
            if make_offer:
                _db_set_session_state(conn, session_id, _make_offer_state(0))
            _db_touch_session(conn, session_id)
            conn.commit()

        _audit("telegram_triage", chat_id=chat_id_str, session_id=session_id,
               intent=intent, offered=make_offer, sources=sources, chunks=len(chunks))

        _send_telegram_message(chat_id, out)

    except TimeoutError:
        logger.error("[telegram] LLM timeout")
        _send_telegram_message(chat_id, _TG_TIMEOUT)
    except Exception as e:
        logger.error(f"[telegram] Unexpected {type(e).__name__}: {e}", exc_info=True)
        _send_telegram_message(chat_id, _TG_ERROR)

    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Instagram DM Webhook  (Sprint 2)
# ─────────────────────────────────────────────────────────────────────────────

# Message-ID dedup cache — prevents double-processing Meta webhook redeliveries.
# Keys: Instagram message-id strings. Values: timestamp of first processing.
_ig_seen_mids: dict[str, float] = {}
_IG_DEDUP_TTL = 300   # seconds; older entries are pruned on each request


def _ig_prune_dedup() -> None:
    """Evict mid entries older than _IG_DEDUP_TTL (called on every webhook)."""
    cutoff = time.time() - _IG_DEDUP_TTL
    stale  = [k for k, v in _ig_seen_mids.items() if v < cutoff]
    for k in stale:
        del _ig_seen_mids[k]


@app.get("/api/webhook/instagram")
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
    if hub_mode == "subscribe" and _secret_eq(hub_verify_token, settings.ig_verify_token):
        logger.info("[instagram] Webhook verified by Meta.")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=hub_challenge or "")
    logger.warning("[instagram] Webhook verification failed — bad verify_token.")
    raise HTTPException(status_code=403, detail="Verification failed.")


def _ig_verify_signature(raw: bytes, header: Optional[str]) -> bool:
    """
    Verify Meta's X-Hub-Signature-256 against the RAW request body.

    Meta computes the HMAC over the EXACT bytes it sent. We must hash those same
    bytes — never a re-serialised copy of the parsed JSON, whose key order,
    spacing, and unicode escaping can differ and break the comparison even when
    the secret is correct. hmac.compare_digest avoids a timing side-channel.
    """
    if not header:
        return False
    expected = "sha256=" + hmac.new(
        settings.ig_app_secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(header, expected)


@app.post("/api/webhook/instagram")
async def instagram_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
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
    if settings.ig_app_secret:
        if not _ig_verify_signature(raw, x_hub_signature_256):
            logger.warning("[instagram] Rejected: bad X-Hub-Signature-256.")
            return {"ok": True}   # 200 but do nothing — never 4xx to Meta

    # ── 2. Parse JSON and offload processing to a worker thread ────────────────
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        logger.warning("[instagram] Could not parse webhook body as JSON.")
        return {"ok": True}

    await run_in_threadpool(_process_instagram_events, body)
    return {"ok": True}


def _process_instagram_events(body: dict) -> None:
    """
    Parse the webhook envelope and dispatch each DM to the funnel handler.
    Runs in a worker thread (offloaded from the async endpoint) so its blocking
    DB / LLM / urllib calls never block the event loop.
    """
    _ig_prune_dedup()
    channel = _INSTAGRAM_CHANNEL

    for entry in (body.get("entry") or []):
        for event in (entry.get("messaging") or []):

            # Sender IGSID — stable identifier for this user+app pair.
            sender_igsid = (event.get("sender") or {}).get("id")
            if not sender_igsid:
                continue

            msg = event.get("message") or {}

            # Drop our own outbound messages echoed back by Meta.
            if msg.get("is_echo"):
                continue

            # ── HARD DROP: story replies / story mentions ─────────────────────
            # A reply to one of our stories (or a story mention) must NEVER be
            # processed — no LLM, no funnel, no reply. This is the #1 authenticity
            # rule: vulnerable story-replies are not leads. Drop at the payload
            # layer, before any handler logic runs.
            if _ig_is_story_message(msg):
                _audit("instagram_story_dropped", igsid=sender_igsid)
                continue

            # Dedup by message-id.
            mid = msg.get("mid")
            if mid:
                if mid in _ig_seen_mids:
                    logger.debug(f"[instagram] Duplicate mid={mid!r} — skipping.")
                    continue
                _ig_seen_mids[mid] = time.time()

            # Resolve the message text. Quick-reply / icebreaker taps may arrive
            # as a payload rather than free text — treat the payload as the text.
            text = (msg.get("text") or "").strip()
            qr_payload = (msg.get("quick_reply") or {}).get("payload", "")
            if not text and qr_payload:
                text = qr_payload

            # Non-text payloads (stickers, voice, images) → silent drop, NO reply.
            if not text:
                _audit("instagram_nontext_dropped", igsid=sender_igsid)
                continue

            # Dispatch to the shared handler (it enforces the deterministic gate).
            _handle_instagram_dm(channel, sender_igsid, text)


# ── Strict deterministic gating (Instagram only) ──────────────────────────────
# On Erez's PERSONAL account the bot must NEVER guess when to stay silent — a
# single wrong reply to a vulnerable story-reply destroys the channel. So the
# cold path uses ZERO LLM evaluation. A cold DM engages the bot ONLY when its
# text exactly matches a configured Instagram Icebreaker; everything else is
# dropped in silence. Story replies/mentions are dropped even earlier, at the
# payload layer (see _ig_is_story_message / _process_instagram_events).

def _ig_icebreaker_set() -> set[str]:
    """The configured Icebreaker texts (trimmed), parsed from IG_ICEBREAKERS."""
    return {
        part.strip()
        for part in (settings.ig_icebreakers or "").split("|")
        if part.strip()
    }


def _ig_is_icebreaker(text: str) -> bool:
    """True iff `text` exactly matches a configured Icebreaker (after trimming)."""
    return (text or "").strip() in _ig_icebreaker_set()


def _ig_trigger_set() -> set[str]:
    """Configured trigger phrases (lowercased, trimmed) from IG_TRIGGER_WORDS."""
    return {
        part.strip().lower()
        for part in (settings.ig_trigger_words or "").split("|")
        if part.strip()
    }


def _ig_matches_trigger(text: str) -> bool:
    """
    True if any configured trigger phrase appears as a SUBSTRING of the message
    (case-insensitive). Substring — not exact / word-boundary — is deliberate:
    Hebrew attaches prefixes (ל-, ב-, ה-) directly to words, so "ייעוץ" must also
    match "לייעוץ" / "הייעוץ". This is how EXISTING followers (who never see the
    native Icebreaker button) enter the funnel. Still ZERO-LLM; story replies are
    hard-dropped before this runs, so it can never fire on a vulnerable share.
    """
    t = (text or "").lower()
    return any(trigger in t for trigger in _ig_trigger_set())


def _ig_is_story_message(msg: dict) -> bool:
    """
    True if this message is a story reply or story mention — which the bot must
    drop instantly and unconditionally (no LLM, no funnel, no reply).

    Detects both shapes Meta uses:
      • story reply:   message.reply_to.story  (replying to one of OUR stories)
      • story mention: an attachment of type 'story_mention'
    """
    if not isinstance(msg, dict):
        return False
    if (msg.get("reply_to") or {}).get("story"):
        return True
    for att in (msg.get("attachments") or []):
        if isinstance(att, dict) and "story" in str(att.get("type", "")).lower():
            return True
    return False


def _handle_instagram_dm(channel: InstagramChannel, igsid: str, text: str) -> None:
    """
    Instagram DM handler with STRICT deterministic gating (personal account).

    Engagement is NEVER decided by an LLM. A message is acted on only when:
      1. it is an active funnel turn (awaiting_qualification / offered_meeting /
         awaiting_contact / awaiting_context for THIS user), or
      2. it exactly matches a configured Instagram Icebreaker (new threads), or
      3. it contains a configured trigger phrase (existing followers — who never
         see the native Icebreaker button).
    Everything else is dropped in total silence. Story replies/mentions are
    dropped even earlier, in _process_instagram_events.

    Instagram-specific funnel adaptations:
      • No /start or /cancel commands (IG DMs have no bot commands).
      • send_contact_prompt() shows a single WhatsApp wa.me button (env-driven;
        falls back to asking for a typed phone when WHATSAPP_NUMBER is unset).

    SAFETY EXCEPTION: crisis/self-harm language in a DIRECT DM still receives the
    compassionate crisis.message (ER"AN hotline) — this is the one deterministic,
    non-LLM reply allowed outside the Icebreaker/funnel paths.
    """
    _audit("instagram_request", igsid=igsid, question=_redact_text(text))

    # ── Rate limit → SILENT drop ───────────────────────────────────────────────
    # A "slow down 🙂" auto-reply to a flooder would reveal automation on a
    # personal account, so we drop silently rather than respond.
    try:
        check_rate_limit(igsid)
    except RateLimitError:
        _audit("instagram_rate_limited_drop", igsid=igsid)
        return

    # ── Crisis — checked first; the one deterministic non-Icebreaker reply ─────
    if is_crisis(text):
        _audit("instagram_crisis", igsid=igsid)
        channel.send_text(igsid, _get_config("crisis.message"))
        prior_state = None
        try:
            with get_db_conn() as conn:
                sid = _db_get_or_create_channel_session(conn, "instagram", igsid)
                prior_state = _db_get_session_state(conn, sid)
                if prior_state:
                    _db_set_session_state(conn, sid, None)
                conn.commit()
        except Exception:
            pass
        # A deferred capture alert must not die with the cleared state — flush
        # it PLAIN. The crisis content itself is never included anywhere.
        if prior_state == "awaiting_context":
            _send_pending_ig_alert(igsid)
        return

    # NOTE: content guards (length / moderation) are deliberately deferred to the
    # cold-message path below. They must run AFTER the funnel state machine so a
    # short in-funnel reply like "כן" (2 chars) is never rejected as "too short"
    # before the offer-classifier sees it — that was the live "Yes → fallback"
    # bug. On a cold message a guard failure becomes a SILENT drop (Silent
    # Filter), not a moderation reply.

    try:
        with get_db_conn() as conn:
            session_id   = _db_get_or_create_channel_session(conn, "instagram", igsid)
            bot_state    = _db_get_session_state(conn, session_id)
            already_lead = _db_has_lead(conn, igsid, channel="instagram")
            history      = _db_load_history(conn, session_id, limit=12)
            conn.commit()

        # ── STATE: awaiting_qualification ─────────────────────────────────────
        if bot_state == "awaiting_qualification":
            if not already_lead:
                with get_db_conn() as conn:
                    _db_save_message(conn, session_id, "user", text)
                    _db_set_session_state(conn, session_id, _make_contact_state(0))
                    _db_touch_session(conn, session_id)
                    conn.commit()
                channel.send_contact_prompt(igsid, _TG_QUALIFICATION_ACK)
                _audit("instagram_qualification_answered", igsid=igsid,
                       session_id=session_id)
                return
            with get_db_conn() as conn:
                _db_set_session_state(conn, session_id, None)
                conn.commit()
            bot_state = None

        # ── STATE: offered_meeting ────────────────────────────────────────────
        if _is_offered_meeting(bot_state):
            if already_lead:
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
                bot_state = None
            else:
                decision, offer_reply = _bot_classify_offer_response(text, history)

                if decision == "AFFIRM":
                    with get_db_conn() as conn:
                        _db_save_message(conn, session_id, "user", text)
                        _db_set_session_state(conn, session_id, _make_contact_state(0))
                        _db_touch_session(conn, session_id)
                        conn.commit()
                    channel.send_contact_prompt(igsid, _TG_OFFER_ACK)
                    _audit("instagram_offer_accepted", igsid=igsid,
                           session_id=session_id)
                    # NEXUS C3 — best-effort, never raises.
                    nexus_hooks.on_funnel_event(
                        "qualified", "instagram", session_id=session_id,
                        stage="qualified", dedup_key=f"qualified:{session_id}")
                    return

                if decision == "DECLINE":
                    with get_db_conn() as conn:
                        _db_save_message(conn, session_id, "user", text)
                        _db_set_session_state(conn, session_id, None)
                        _db_touch_session(conn, session_id)
                        conn.commit()
                    channel.send_text(igsid, _TG_OFFER_DECLINED)
                    _audit("instagram_offer_declined", igsid=igsid,
                           session_id=session_id)
                    return

                count = _parse_offer_count(bot_state)
                with get_db_conn() as conn:
                    _db_save_message(conn, session_id, "user", text)
                    if count + 1 < _MAX_REOFFERS:
                        out = (f"{offer_reply}\n\n{_TG_MEETING_CTA}".strip()
                               if offer_reply else _TG_MEETING_CTA)
                        _db_set_session_state(conn, session_id,
                                              _make_offer_state(count + 1))
                    else:
                        out = offer_reply or _TG_OFFER_BACKOFF
                        _db_set_session_state(conn, session_id, None)
                    _db_save_message(conn, session_id, "assistant", out)
                    _db_touch_session(conn, session_id)
                    conn.commit()
                channel.send_text(igsid, out)
                _audit("instagram_offer_other", igsid=igsid,
                       session_id=session_id, reoffers=count + 1)
                return

        # ── Escape-intent gate ────────────────────────────────────────────────
        if bot_state and _is_escape_intent(text):
            with get_db_conn() as conn:
                _db_set_session_state(conn, session_id, None)
                conn.commit()
            channel.send_text(igsid, _TG_ESCAPE_RESPONSE)
            _audit("instagram_escape", igsid=igsid, prior_state=bot_state)
            if bot_state == "awaiting_context":
                # Declining the optional topic question still alerts Erez —
                # plain alert, no brief.
                _send_pending_ig_alert(igsid)
            return

        # ── STATE: awaiting_contact ───────────────────────────────────────────
        # On Instagram: typed phone is always accepted as a direct capture path.
        # The send_contact_prompt call above showed the WhatsApp wa.me button
        # as the primary CTA. If the user types a phone number instead,
        # here instead, we capture it exactly as Telegram does.
        if _is_awaiting_contact(bot_state):
            phone = _extract_phone_from_text(text)
            retry = _parse_contact_retry(bot_state)

            if already_lead:
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
                bot_state = None
            elif phone:
                try:
                    intent_summary = _build_intent_summary(history, text)
                    with get_db_conn() as conn:
                        lead_id = _db_save_lead(conn, session_id, igsid,
                                                None, phone, intent_summary,
                                                channel="instagram")
                        # New lead → advance to awaiting_context to collect ONE
                        # optional topic line (capture-first, enrich-second).
                        # Duplicate (lead_id None) → just clear the state.
                        _db_set_session_state(
                            conn, session_id,
                            "awaiting_context" if lead_id else None)
                        conn.commit()
                    if lead_id:
                        # Thanks + a soft, optional topic question in one message.
                        channel.send_text(igsid, _IG_LEAD_THANKS_CONTEXT)
                        # Alert unification: defer the owner alert — Erez gets
                        # ONE combined message (details + 🧠 brief) at the
                        # context turn; exit-path flushes + the cron backstop
                        # guarantee it is delayed, never lost.
                        _finalize_lead(lead_id, None, phone, intent_summary, igsid,
                                       channel="instagram",
                                       defer_owner_alert=True)
                        _audit("instagram_lead_captured", igsid=igsid, lead_id=lead_id)
                        _track("lead_captured", "instagram",
                               session_id=session_id, lead_id=lead_id)
                except Exception as e:
                    logger.error(f"[instagram] awaiting_contact: {e}", exc_info=True)
                    channel.send_text(igsid, _IG_ERROR)
                return
            elif retry >= _MAX_CONTACT_RETRIES:
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
                channel.send_text(igsid, _TG_CONTACT_RETRY_EXHAUSTED)
                _audit("instagram_contact_exhausted", igsid=igsid)
                return
            else:
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id,
                                          _make_contact_state(retry + 1))
                    conn.commit()
                # Re-ask for the WhatsApp number in plain text (this flow collects
                # the prospect's number; it does not hand out a wa.me link).
                channel.send_text(igsid, _IG_CONTACT_RETRY)
                return

        # ── STATE: awaiting_context (post-capture enrichment) ──────────────────
        # The lead is ALREADY captured, alerted, and synced — this single optional
        # turn collects one topic line so we can build a Lead Brief. Because the
        # crisis check ran first (top of the handler), an acute disclosure here is
        # met with the ER"AN response, never a CRM brief. Reached only after the
        # escape gate (a short "לא" opts out cleanly); a real sentence flows here.
        if bot_state == "awaiting_context":
            with get_db_conn() as conn:
                _db_save_message(conn, session_id, "user", text)
                _db_set_session_state(conn, session_id, None)   # one-shot
                _db_touch_session(conn, session_id)
                conn.commit()
            # Only spend an LLM call when there's something to analyse.
            if len(text.strip()) >= 4:
                _track("context_provided", "instagram", session_id=session_id)
                _audit("instagram_context_provided", igsid=igsid, session_id=session_id)
                # NEXUS C5 — post-capture enrichment landed → 'briefed'.
                nexus_hooks.on_funnel_event(
                    "context_provided", "instagram", session_id=session_id,
                    stage="briefed", dedup_key=f"context:{session_id}")
                try:
                    _deliver_lead_brief(igsid, text, history)   # best-effort
                except Exception as e:
                    logger.error(f"[brief] delivery failed for {igsid}: {e}")
            else:
                # Too short to brief — close the window with the PLAIN alert.
                _send_pending_ig_alert(igsid)
            channel.send_text(igsid, _IG_CONTEXT_ACK)
            return

        # ─────────────────────────────────────────────────────────────────────
        # COLD MESSAGE (no active funnel state consumed it above).
        #
        # STRICT DETERMINISTIC GATE — ZERO LLM. The bot engages on exactly two
        # signals, both deterministic:
        #   • an exact Instagram Icebreaker match  → new-thread followers
        #   • a configured trigger phrase (substring) → EXISTING followers, who
        #     never see the native Icebreaker button
        # Everything else (random text, "hi", info questions, vulnerable shares)
        # is dropped in total silence. This is the authenticity guarantee.
        # ─────────────────────────────────────────────────────────────────────
        entry = ("icebreaker"   if _ig_is_icebreaker(text)
                 else "trigger_word" if _ig_matches_trigger(text)
                 else None)
        if entry:
            if already_lead:
                reply_text  = _IG_ALREADY_LEAD_REPLY
                new_state   = None
                audit_event = "instagram_already_lead_icebreaker"
            else:
                # Warm first-person reply that asks directly for the WhatsApp
                # number, and jump STRAIGHT to awaiting_contact — so the user's
                # next message (their number) is captured as a lead with no
                # intermediate qualification step.
                # The icebreaker reply IS the WhatsApp-number ask → attach the
                # M4 consent line here (the IG collection point).
                reply_text  = _IG_ICEBREAKER_REPLY + _config_suffix("consent.capture_line")
                new_state   = _make_contact_state(0)
                audit_event = "instagram_funnel_entry"
            with get_db_conn() as conn:
                _db_save_message(conn, session_id, "user", text)
                _db_save_message(conn, session_id, "assistant", reply_text)
                if new_state:
                    _db_set_session_state(conn, session_id, new_state)
                _db_touch_session(conn, session_id)
                conn.commit()
            channel.send_text(igsid, reply_text)
            _audit(audit_event, igsid=igsid, session_id=session_id, entry=entry)
            # entry source is tagged in meta so the dashboard can later split
            # new-thread (icebreaker) vs existing-follower (trigger_word) funnels.
            _track("icebreaker_hit", "instagram", session_id=session_id,
                   returning_lead=already_lead, entry=entry)
            # NEXUS C1 — funnel entry on Instagram. A returning lead whose
            # previous episode was CLOSED gets a fresh opportunity (genuine
            # re-engagement); an open episode is simply reused. Best-effort.
            nexus_hooks.on_funnel_event(
                "icebreaker_hit" if entry == "icebreaker" else "trigger_hit",
                "instagram", session_id=session_id, stage="engaged",
                payload={"entry": entry, "returning_lead": already_lead})
            if already_lead:
                # A previously-captured lead resurfacing: if their deferred
                # alert never fired (they ghosted the context question), flush
                # it now instead of waiting for the daily backstop.
                _send_pending_ig_alert(igsid)
            return

        # Neither an Icebreaker, a trigger phrase, nor an active-funnel turn
        # → stay 100% silent.
        _audit("instagram_silent_drop", igsid=igsid, reason="no_trigger")
        return

    except TimeoutError:
        logger.error("[instagram] LLM timeout")
        channel.send_text(igsid, _IG_TIMEOUT)
    except Exception as e:
        logger.error(f"[instagram] Unexpected {type(e).__name__}: {e}", exc_info=True)
        channel.send_text(igsid, _IG_ERROR)


# ═══════════════════════════════════════════════════════════════════════════════
# WhatsApp Business Cloud API channel (Sprint 4, Ticket 4.1 — plumbing/parity)
# ───────────────────────────────────────────────────────────────────────────────
# Peer to the Telegram and Instagram channels above: same MessagingChannel seam,
# the same Meta X-Hub-Signature-256 verification as Instagram, and the same
# channel-agnostic session + person-spine wiring — _db_get_or_create_channel_session
# calls Hook A internally, so resolving a 'whatsapp' session resolves the person.
#
# 4.1 proves the wire: inbound WA message → signature-checked → person resolved →
# read receipt + placeholder reply sent via the Cloud API. The qualification
# state machine (story → insight → interest → price) attaches at the marked seam
# in _handle_whatsapp_message in Ticket 4.2.
#
# Cloud API specifics vs Instagram:
#   • Send host is graph.facebook.com/<PHONE_NUMBER_ID>/messages with a Bearer
#     token (IG uses graph.instagram.com/me/messages with ?access_token=).
#   • Inbound envelope is entry[].changes[].value.messages[] (delivery/read
#     receipts arrive as value.statuses[] and carry no 'messages' → skipped).
#   • The sender id (msg["from"]) is the user's wa_id — their phone in E.164
#     without '+', which is exactly the external_id for channel='whatsapp'.
# ═══════════════════════════════════════════════════════════════════════════════

_WA_API_VERSION = "v21.0"   # match the IG Graph version already in use


def _wa_graph_call(payload: dict) -> Optional[str]:
    """
    POST to the WhatsApp Cloud API /messages endpoint. Best-effort, mirrors
    _ig_graph_call: stdlib urllib only, never raises (the webhook must always
    return 200). On failure the Cloud API error body is logged — it carries the
    actionable reason (token scope, 24h-window, bad recipient).
    """
    if not (settings.whatsapp_phone_number_id and settings.whatsapp_access_token):
        logger.error("[whatsapp] WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN "
                     "not set — cannot send.")
        return None
    url = (f"https://graph.facebook.com/{_WA_API_VERSION}/"
           f"{settings.whatsapp_phone_number_id}/messages")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type":  "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception as e:
        detail = ""
        read = getattr(e, "read", None)
        if callable(read):
            try:
                detail = read().decode("utf-8", "ignore")
            except Exception:
                detail = ""
        logger.error(f"[whatsapp] Cloud API send failed: {e} {detail}".strip())
        return None


class WhatsAppChannel(MessagingChannel):
    """
    WhatsApp Business Cloud API via graph.facebook.com.

    4.1 implements send_text (the qualification flow's hot path) plus read
    receipts; send_quick_replies / send_buttons have working implementations so
    the MessagingChannel contract is honoured and 4.2/4.3 can use them. WhatsApp
    text bodies cap at 4096 chars.
    """

    CHANNEL_NAME = "whatsapp"

    def send_text(self, recipient_id: str, text: str) -> None:
        body = (text or "").strip()[:4096] or "…"
        _wa_graph_call({
            "messaging_product": "whatsapp",
            "recipient_type":    "individual",
            "to":                recipient_id,
            "type":              "text",
            "text":              {"preview_url": False, "body": body},
        })

    def send_quick_replies(self, recipient_id: str, text: str,
                           replies: list[dict]) -> None:
        # WhatsApp interactive reply buttons (max 3). With none or >3 options,
        # degrade to plain text so the funnel never wedges.
        btns = replies[:3]
        if not btns:
            self.send_text(recipient_id, text)
            return
        _wa_graph_call({
            "messaging_product": "whatsapp",
            "recipient_type":    "individual",
            "to":                recipient_id,
            "type":              "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": (text or "").strip()[:1024] or "…"},
                "action": {"buttons": [
                    {"type": "reply", "reply": {
                        "id":    str(r.get("payload", r["title"]))[:256],
                        "title": r["title"][:20]}}
                    for r in btns
                ]},
            },
        })

    def send_buttons(self, recipient_id: str, text: str,
                     buttons: list[dict]) -> None:
        # No multi-URL button template in the free-form window — send the text
        # with any URL inline (WhatsApp auto-links it). 4.3 may upgrade the
        # Calendly handoff to a native interactive cta_url message.
        lines = [(text or "").strip()]
        for b in buttons:
            if b.get("type") == "web_url" and b.get("url"):
                lines.append(f'{b.get("title", "")}: {b["url"]}'.strip())
        self.send_text(recipient_id, "\n".join(ln for ln in lines if ln))

    def send_contact_prompt(self, recipient_id: str, preamble: str) -> None:
        # On WhatsApp the person is already reachable on this number — there is no
        # separate contact-share step (unlike Telegram/Instagram). The price →
        # Calendly handoff (Ticket 4.3) replaces the IG/TG contact CTA here.
        consent = _config_suffix("consent.capture_line")
        self.send_text(recipient_id, f"{preamble}{consent}")

    def mark_read(self, message_id: str) -> None:
        """Blue-tick read receipt (best-effort). WhatsApp keys this on the
        inbound message id, so it lives here rather than the base mark_seen."""
        if not message_id:
            return
        _wa_graph_call({
            "messaging_product": "whatsapp",
            "status":            "read",
            "message_id":        message_id,
        })


_WHATSAPP_CHANNEL = WhatsAppChannel()


# ── Inbound dedup (Meta redelivers; schema-level idempotency is the real guard) ─
_wa_seen_mids: dict[str, float] = {}
_WA_DEDUP_TTL = 300   # seconds; pruned each request, mirrors the IG dedup window


def _wa_prune_dedup() -> None:
    cutoff = time.time() - _WA_DEDUP_TTL
    for k in [k for k, v in _wa_seen_mids.items() if v < cutoff]:
        del _wa_seen_mids[k]


def _wa_verify_signature(raw: bytes, header: Optional[str]) -> bool:
    """X-Hub-Signature-256 over the RAW body with WHATSAPP_APP_SECRET — identical
    scheme to Instagram (_ig_verify_signature)."""
    if not header:
        return False
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(header, expected)


@app.get("/api/webhook/whatsapp")
def whatsapp_webhook_verify(request: Request):
    """
    Meta webhook verification handshake (GET), one-time at subscription.
    Meta sends ?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<int>.
    Read straight from query_params — the dotted keys ('hub.mode') do not bind to
    Python parameter names, so this is the robust way to read them. Echo the
    challenge as plain text on success.
    """
    qp = request.query_params
    if (qp.get("hub.mode") == "subscribe"
            and _secret_eq(qp.get("hub.verify_token"), settings.whatsapp_verify_token)):
        logger.info("[whatsapp] Webhook verified by Meta.")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=qp.get("hub.challenge") or "")
    logger.warning("[whatsapp] Webhook verification failed — bad verify_token.")
    raise HTTPException(status_code=403, detail="Verification failed.")


@app.post("/api/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    """
    WhatsApp Cloud API webhook — POST handler. async so we can hash the RAW body
    (await request.body()) against Meta's HMAC before parsing. Blocking work is
    offloaded to a worker thread. Always returns 200 so Meta never retries into a
    duplicate-message storm. Mirrors the Instagram webhook exactly.
    """
    raw = await request.body()

    if settings.whatsapp_app_secret:
        if not _wa_verify_signature(raw, x_hub_signature_256):
            logger.warning("[whatsapp] Rejected: bad X-Hub-Signature-256.")
            return {"ok": True}   # 200 but do nothing — never 4xx to Meta

    try:
        body = json.loads(raw or b"{}")
    except Exception:
        logger.warning("[whatsapp] Could not parse webhook body as JSON.")
        return {"ok": True}

    await run_in_threadpool(_process_whatsapp_events, body)
    return {"ok": True}


def _wa_extract_text(msg: dict) -> str:
    """Best-effort plain text from a WhatsApp inbound message. Text bodies and
    interactive/button replies become text (the reply id is the payload);
    everything else (media, location, …) returns '' → silent drop in 4.1."""
    mtype = msg.get("type")
    if mtype == "text":
        return (msg.get("text") or {}).get("body", "") or ""
    if mtype == "interactive":
        inter = msg.get("interactive") or {}
        node  = inter.get("button_reply") or inter.get("list_reply") or {}
        return node.get("id") or node.get("title") or ""
    if mtype == "button":
        return (msg.get("button") or {}).get("text", "") or ""
    return ""


def _process_whatsapp_events(body: dict) -> None:
    """
    Parse the Cloud API envelope (entry[].changes[].value.messages[]) and
    dispatch each inbound text to the handler. Runs in a worker thread. Status
    callbacks (value.statuses[]) carry no 'messages' and are skipped.
    """
    _wa_prune_dedup()
    channel = _WHATSAPP_CHANNEL

    for entry in (body.get("entry") or []):
        for change in (entry.get("changes") or []):
            value = change.get("value") or {}
            for msg in (value.get("messages") or []):
                wa_from = msg.get("from")
                mid     = msg.get("id")
                if not wa_from or not mid:
                    continue

                # Dedup by message id (Meta redelivery / cold-start replays).
                if mid in _wa_seen_mids:
                    logger.debug(f"[whatsapp] Duplicate id={mid!r} — skipping.")
                    continue
                _wa_seen_mids[mid] = time.time()

                text = _wa_extract_text(msg).strip()
                if not text:
                    _audit("whatsapp_nontext_dropped", wa_id=wa_from)
                    continue

                _handle_whatsapp_message(channel, wa_from, text, mid)


# ═══════════════════════════════════════════════════════════════════════════════
# WhatsApp qualification state machine (Ticket 4.2 — WhatsApp-only)
# ───────────────────────────────────────────────────────────────────────────────
# Psychological flow (Erez's DNA): Understanding → Insight → Invitation →
# (wait for signal) → Price. Empathy and price NEVER share a message. Only the
# insight (State 2) is AI-generated; the opening, bridge, offer, price and
# Calendly lead-in are hardcoded copy (live-editable in app_config). The crisis
# gate in _handle_whatsapp_message runs upstream of every state here, so a
# distress 'story' is routed to the hotline before any insight is generated.
#
# States ride the existing sessions.bot_state TTL machine (24h = the WhatsApp
# service window) and are wa_-prefixed so they never collide with the Telegram
# funnel's states (Telegram keeps its own flow untouched for now).
# ═══════════════════════════════════════════════════════════════════════════════

_WA_STATE_STORY    = "wa_awaiting_story"
_WA_STATE_INTEREST = "wa_awaiting_interest"
_WA_STATE_PRICE    = "wa_offered_price"

# Anti-cringe guard: the insight prompt forbids these, AND the output is checked
# against them in CODE (prompt-only is not a guarantee). Matched normalized +
# substring, so spacing/punctuation variants are still caught.
_WA_BANNED_PHRASES = (
    "אני מבין בדיוק מה אתה עובר",
    "אני מבינה בדיוק מה את עוברת",
    "אל תדאג יש לי פתרון",
    "יש לי פתרון",
    "הרבה אנשים במצב שלך",
)


def _wa_normalize(s: str) -> str:
    """Collapse whitespace for a forgiving banned-phrase substring check."""
    return re.sub(r"\s+", " ", (s or "")).strip()


def _wa_insight_is_clean(text: str) -> bool:
    """True iff the generated insight is non-empty and contains none of the
    banned generic-therapist phrases."""
    norm = _wa_normalize(text)
    return bool(norm) and not any(_wa_normalize(b) in norm for b in _WA_BANNED_PHRASES)


def _wa_generate_insight(story: str) -> str:
    """
    State 2 — reflect the user's internal conflict (one of three axes), no
    solutions. AI-generated, then guarded in code: if the output trips the
    anti-cringe list it is regenerated once, then falls back to a safe neutral
    reflection. The instructions live in app_config ('whatsapp.insight_
    instructions'); the story is appended in code (never .format-ed) so a live
    edit can't break templating.
    """
    prompt = (
        f"{_get_config('whatsapp.insight_instructions')}\n\n"
        f"מה שהמשתמש כתב:\n{(story or '').strip()[:1500]}\n\n"
        f"התובנה שלך (משפט אחד או שניים בלבד):"
    )
    for attempt in range(2):
        try:
            insight = _truncate_reply((_call_llm(prompt) or "").strip())
        except Exception as e:
            logger.warning(f"[whatsapp] insight generation failed: {e}")
            break
        if _wa_insight_is_clean(insight):
            return insight
        logger.info("[whatsapp] insight rejected by anti-cringe guard (attempt %d)",
                    attempt + 1)
    return _get_config("whatsapp.insight_fallback")


def _wa_send_and_persist(channel: MessagingChannel, wa_id: str, session_id: str,
                         reply: str, new_state: Optional[str]) -> None:
    """Persist the assistant message + set/clear bot_state, then send — the
    DB-then-send order used by the Telegram/Instagram funnel branches."""
    try:
        with get_db_conn() as conn:
            _db_save_message(conn, session_id, "assistant", reply)
            _db_set_session_state(conn, session_id, new_state)
            _db_touch_session(conn, session_id)
            conn.commit()
    except Exception as e:
        logger.warning(f"[whatsapp] persist/setstate failed: {e}")
    channel.send_text(wa_id, reply)


def _wa_run_qualification(channel: MessagingChannel, wa_id: str, session_id: str,
                          text: str, bot_state: Optional[str],
                          history: list) -> None:
    """The WhatsApp funnel. Crisis already handled upstream by the caller."""

    # ── State 4: price offered — waiting for a yes ────────────────────────────
    if bot_state == _WA_STATE_PRICE:
        decision, _ = _bot_classify_offer_response(text, history)
        if decision == "AFFIRM":
            link  = _get_config("calendly.url").strip()
            lead  = _get_config("whatsapp.booking_leadin")
            reply = f"{lead}\n{link}" if link else lead
            _wa_send_and_persist(channel, wa_id, session_id, reply, None)
            nexus_hooks.on_funnel_event(
                "qualified", "whatsapp", session_id=session_id,
                stage="qualified", dedup_key=f"qualified:{session_id}")
            _audit("whatsapp_price_accepted", wa_id=wa_id, session_id=session_id)
        elif decision == "DECLINE":
            _wa_send_and_persist(channel, wa_id, session_id,
                                 _get_config("whatsapp.decline"), None)
            _audit("whatsapp_price_declined", wa_id=wa_id, session_id=session_id)
        else:
            _wa_send_and_persist(channel, wa_id, session_id,
                                 _get_config("whatsapp.price_nudge"), _WA_STATE_PRICE)
            _audit("whatsapp_price_other", wa_id=wa_id, session_id=session_id)
        return

    # ── State 3: invitation sent — waiting for the interest signal ────────────
    if bot_state == _WA_STATE_INTEREST:
        decision, _ = _bot_classify_offer_response(text, history)
        if decision == "DECLINE":
            _wa_send_and_persist(channel, wa_id, session_id,
                                 _get_config("whatsapp.decline"), None)
            _audit("whatsapp_interest_declined", wa_id=wa_id, session_id=session_id)
        else:
            # AFFIRM or OTHER — a question is still engagement; the price message
            # answers the common ones (duration, 1-on-1, cost). Never push price
            # on an explicit decline, which is the branch above.
            _wa_send_and_persist(channel, wa_id, session_id,
                                 _get_config("whatsapp.price_offer"), _WA_STATE_PRICE)
            _audit("whatsapp_interest_signal", wa_id=wa_id,
                   session_id=session_id, decision=decision)
        return

    # ── State 2: the user just told their story → reflect + bridge ────────────
    if bot_state == _WA_STATE_STORY:
        insight = _wa_generate_insight(text)
        reply   = f"{insight}\n\n{_get_config('whatsapp.bridge')}"
        _wa_send_and_persist(channel, wa_id, session_id, reply, _WA_STATE_INTEREST)
        _audit("whatsapp_insight_sent", wa_id=wa_id, session_id=session_id)
        return

    # ── Entry: first contact (or expired state) → the opening ─────────────────
    _wa_send_and_persist(channel, wa_id, session_id,
                         _get_config("whatsapp.opening"), _WA_STATE_STORY)
    nexus_hooks.on_funnel_event(
        "engaged", "whatsapp", session_id=session_id, stage="engaged",
        dedup_key=f"engaged:{session_id}")
    _audit("whatsapp_funnel_opened", wa_id=wa_id, session_id=session_id)


def _handle_whatsapp_message(channel: MessagingChannel, wa_id: str,
                             text: str, mid: str) -> None:
    """
    Ticket 4.2 — crisis gate (shared is_crisis) → read receipt → channel-agnostic
    session + person-spine resolution (Hook A rides inside
    _db_get_or_create_channel_session) → persist inbound → run the qualification
    state machine. WhatsApp-only; Telegram/Instagram funnels are untouched.
    """
    _audit("whatsapp_request", wa_id=wa_id, question=_redact_text(text))

    try:
        check_rate_limit(wa_id)
    except RateLimitError:
        _audit("whatsapp_rate_limited_drop", wa_id=wa_id)
        return

    # ── Crisis — checked FIRST, upstream of every funnel/insight branch. ──
    if is_crisis(text):
        _audit("whatsapp_crisis", wa_id=wa_id)
        channel.send_text(wa_id, _get_config("crisis.message"))
        try:
            with get_db_conn() as conn:
                sid = _db_get_or_create_channel_session(conn, "whatsapp", wa_id)
                if _db_get_session_state(conn, sid):
                    _db_set_session_state(conn, sid, None)
                conn.commit()
        except Exception:
            pass
        return

    channel.mark_read(mid)   # best-effort blue tick

    try:
        with get_db_conn() as conn:
            session_id = _db_get_or_create_channel_session(conn, "whatsapp", wa_id)
            bot_state  = _db_get_session_state(conn, session_id)
            history    = _db_load_history(conn, session_id, limit=12)
            _db_save_message(conn, session_id, "user", text)
            _db_touch_session(conn, session_id)
            conn.commit()
    except Exception as e:
        logger.warning(f"[whatsapp] session resolve failed for {wa_id[:6]}…: {e}")
        return

    _wa_run_qualification(channel, wa_id, session_id, text, bot_state, history)


@app.get("/api/powerbi/config", dependencies=[Depends(require_auth)])
def powerbi_config():
    """
    Return the Power BI embed URL, built from server-side env vars, to
    AUTHENTICATED callers only. This keeps the Azure tenant id (ctid) and report
    id OUT of the public JS bundle, where they would otherwise be harvestable for
    AD-tenant enumeration. Returns 503 when not configured so the frontend can
    degrade gracefully.

    NOTE: this is the interim hardening. The full fix is a server-generated embed
    token via an Azure service principal (removes autoAuth entirely) — scoped as
    the next step.
    """
    if not (settings.powerbi_report_id and settings.powerbi_tenant_id):
        raise HTTPException(status_code=503, detail="Power BI not configured.")
    embed_url = (
        "https://app.powerbi.com/reportEmbed"
        f"?reportId={settings.powerbi_report_id}"
        "&autoAuth=true"
        f"&ctid={settings.powerbi_tenant_id}"
    )
    return {"embed_url": embed_url}


@app.get("/api/metrics", dependencies=[Depends(require_auth)])
def get_metrics(days: int = 30, channel: Optional[str] = None):
    """
    Conversion-funnel metrics from bot_events.

    Returns icebreaker hits, lead captures, and the conversion rate over the
    last `days` (clamped to 1..365), optionally filtered to one channel.
    Read-only; never writes. Behind require_auth like the other data endpoints.
    """
    days = max(1, min(int(days), 365))
    params: list = [days]
    channel_clause = ""
    if channel:
        channel_clause = "AND channel = %s"
        params.append(channel)

    counts: dict = {}
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT event, COUNT(*) FROM bot_events "
                    f"WHERE ts >= NOW() - make_interval(days => %s) {channel_clause} "
                    f"GROUP BY event",
                    tuple(params),
                )
                counts = {row[0]: int(row[1]) for row in cur.fetchall()}
    except Exception as e:
        logger.error(f"[metrics] query failed: {e}")
        raise HTTPException(status_code=500, detail="Metrics unavailable.")

    hits        = counts.get("icebreaker_hit", 0)
    captures    = counts.get("lead_captured", 0)
    context_n   = counts.get("context_provided", 0)
    rate        = round(captures / hits, 4) if hits else 0.0
    context_rate = round(context_n / captures, 4) if captures else 0.0
    return {
        "window_days":      days,
        "channel":          channel or "all",
        "icebreaker_hits":  hits,
        "lead_captures":    captures,
        "conversion_rate":  rate,          # captures / hits
        "context_provided": context_n,
        "context_rate":     context_rate,  # context_provided / captures (downstream)
    }


@app.get("/api/metrics/bookings", dependencies=[Depends(require_auth)])
def get_booking_metrics():
    """
    The North Star, observable: booked consultations. 'booked_this_week' counts
    scheduled bookings created since the start of the ISO week — canceled ones
    drop out (status filter), which is exactly how cancellations are netted out
    without touching the forward-only opportunity stage. matched/unmatched shows
    how many auto-linked to a person vs. await a manual link in the cockpit.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    " count(*) FILTER (WHERE status='scheduled' "
                    "   AND created_at >= date_trunc('week', NOW())) AS booked_this_week, "
                    " count(*) FILTER (WHERE status='scheduled') AS scheduled_total, "
                    " count(*) FILTER (WHERE status='canceled')  AS canceled_total, "
                    " count(*) FILTER (WHERE person_id IS NOT NULL) AS matched, "
                    " count(*) FILTER (WHERE person_id IS NULL)     AS unmatched "
                    "FROM bookings")
                row = cur.fetchone()
        return {
            "booked_this_week": row[0], "scheduled_total": row[1],
            "canceled_total":   row[2], "matched": row[3], "unmatched": row[4],
        }
    except Exception as e:
        logger.error(f"[metrics] bookings query failed: {e}")
        raise HTTPException(status_code=500, detail="Booking metrics unavailable.")


@app.post("/api/webhooks/calendly")
async def calendly_webhook(
    request: Request,
    calendly_webhook_signature: Optional[str] = Header(default=None),
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

    if settings.calendly_webhook_signing_key:
        if not nexus_bookings.verify_signature(
                raw, calendly_webhook_signature,
                settings.calendly_webhook_signing_key):
            logger.warning("[calendly] rejected webhook: bad/missing signature.")
            return {"ok": True}
    elif os.environ.get("VERCEL"):
        logger.error("[calendly] SIGNING_KEY not set — webhook disabled in production.")
        return {"ok": True}

    try:
        body = json.loads(raw or b"{}")
    except Exception:
        logger.warning("[calendly] could not parse webhook body as JSON.")
        return {"ok": True}

    await run_in_threadpool(nexus_bookings.process_event, body)
    return {"ok": True}


@app.delete("/api/person/{person_id}", dependencies=[Depends(require_auth)])
def erase_person_endpoint(person_id: str, confirm: bool = False):
    """
    Right-to-be-forgotten (Ticket 3.7). HARD-deletes a person and ALL their data
    — identities, profile, memory, sessions, messages, leads, opportunities,
    bookings, interactions — in one transaction, then logs the erasure (UUID +
    counts, no PII) to erasure_log.

    DESTRUCTIVE + IRREVERSIBLE, so: behind require_auth (operator-only — a public
    erasure route would let anyone delete anyone) AND requires ?confirm=true.
    404 if the person doesn't exist (idempotent — already-erased is a no-op).
    """
    try:
        uuid.UUID(person_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail="Person not found.")
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Erasure is irreversible — repeat the request with ?confirm=true.")
    try:
        with get_db_conn() as conn:
            counts = nexus_erasure.erase_person(conn, person_id, requested_by="api")
            if counts is None:
                raise HTTPException(status_code=404, detail="Person not found.")
            conn.commit()
        _audit("person_erased", person_id=person_id, counts=counts)
        return {"status": "erased", "person_id": person_id, "deleted": counts}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[erasure] failed for {person_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erasure failed.")


@app.get("/api/cron/crm-sync")
def cron_crm_sync(
    authorization: Optional[str] = Header(default=None),
    x_cron_secret: Optional[str] = Header(default=None),
):
    """
    Reconciliation job — retries the CRM push for any lead committed to Supabase
    but never synced (crm_synced_at IS NULL), e.g. because the CRM was down during
    live capture. Triggered by Vercel Cron (see vercel.json).

    Auth: guarded by CRON_SECRET. Vercel Cron sends it as
    'Authorization: Bearer <secret>'; we also accept an X-Cron-Secret header for
    manual curl.

    FAIL-CLOSED: on a Vercel deployment (VERCEL env var is set) the endpoint
    requires CRON_SECRET to be configured. If it is not set in production the
    endpoint returns 503 rather than silently allowing unauthenticated access
    (which could be used to spam HubSpot or exhaust the DB connection pool).
    Locally (no VERCEL env var) the guard is skipped for development convenience.

    Batched (LIMIT 50) so a backlog can't exceed the function time budget.
    """
    if settings.cron_secret:
        bearer = (authorization or "")
        if bearer.startswith("Bearer "):
            bearer = bearer[len("Bearer "):].strip()
        if not (_secret_eq(bearer, settings.cron_secret)
                or _secret_eq(x_cron_secret, settings.cron_secret)):
            raise HTTPException(status_code=401, detail="Invalid cron secret.")
    elif os.environ.get("VERCEL"):
        # Production but CRON_SECRET not set — fail closed rather than allow
        # unauthenticated invocations that waste HubSpot quota / DB connections.
        logger.error("[cron] CRON_SECRET is not set — endpoint disabled in production. "
                     "Set CRON_SECRET in Vercel env vars.")
        raise HTTPException(status_code=503, detail="Cron endpoint not configured.")

    # ── Deferred-alert backstop (Instagram alert unification) ─────────────────
    # IG capture alerts are deferred to the context turn; a lead who never
    # sends another message would otherwise never alert. Sweep anything
    # unnotified for >30 minutes and send the PLAIN alert. Channel-agnostic on
    # purpose: it also retries any lead whose inline alert failed (e.g. a
    # Telegram outage at capture time). Runs BEFORE the CRM gate — alerts must
    # not depend on a CRM being configured.
    alerts_sent = 0
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, chat_id, channel, name, phone, intent_summary "
                    "FROM leads WHERE notified_at IS NULL "
                    "AND created_at < NOW() - INTERVAL '30 minutes' "
                    "ORDER BY created_at LIMIT 20"
                )
                unalerted = cur.fetchall()
        for lid, cid, ch, nm, ph, summ in unalerted:
            username = _ig_fetch_username(cid) if ch == "instagram" else None
            message_id = _alert_owner(str(lid), nm, ph, summ, cid,
                                      channel=ch, username=username)
            with get_db_conn() as conn:
                _db_mark_lead_notified(conn, str(lid))
                _db_set_lead_alert_message_id(conn, str(lid), message_id)
                conn.commit()
            alerts_sent += 1
        if alerts_sent:
            _audit("alert_backstop", alerts_sent=alerts_sent)
    except Exception as e:
        logger.error(f"[cron] alert backstop failed: {e}")

    if not _crm_enabled():
        return {"status": "skipped", "reason": "CRM not configured",
                "alerts_sent": alerts_sent}

    synced, failed = 0, 0
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, phone, intent_summary, channel, chat_id "
                    "FROM leads WHERE crm_synced_at IS NULL "
                    "ORDER BY created_at LIMIT 50"
                )
                pending = cur.fetchall()

        for lead_id, name, phone, intent, channel, chat_id in pending:
            # Pass channel + chat_id so the backstop applies the same channel
            # tagging + Instagram-id/username dedup as the inline path.
            external_id = _crm_sync_lead(name, phone, intent, channel=channel,
                                         external_user_id=chat_id)
            if external_id:
                with get_db_conn() as conn:
                    _db_mark_lead_synced(conn, str(lead_id), external_id)
                    conn.commit()
                synced += 1
            else:
                failed += 1

        _audit("crm_reconcile", pending=len(pending), synced=synced, failed=failed)
        return {"status": "ok", "pending": len(pending),
                "synced": synced, "failed": failed,
                "alerts_sent": alerts_sent}
    except Exception as e:
        logger.error(f"[crm] reconcile failed: {e}", exc_info=True)
        return {"status": "error", "detail": "reconcile failed"}


# ─── Memory formation — shadow mode (Ticket 3.5, Phase 1) ─────────────────────
# Two independent switches, both read live from app_config (no redeploy to flip):
#   memory.formation_enabled — the background sweep writes profiles/summaries.
#   memory.recall_enabled    — memory is injected back into the bot prompt.
# Phase 1 = formation ON, recall OFF: the system silently builds memory without
# touching the bot's live voice. Defaults are OFF when the key is absent, so the
# feature is dormant until explicitly enabled.

def _flag_on(key: str) -> bool:
    return _get_config(key).strip().lower() == "true"

def _memory_formation_on() -> bool:
    return _flag_on("memory.formation_enabled")

def _memory_recall_on() -> bool:
    return _flag_on("memory.recall_enabled")


@app.get("/api/cron/memory-sweep")
def cron_memory_sweep(
    authorization: Optional[str] = Header(default=None),
    x_cron_secret: Optional[str] = Header(default=None),
):
    """
    Shadow-mode memory formation sweep. Summarises idle, unsummarised sessions
    that carry a real conversation, writing session_summaries + person_profile
    and NOTHING user-facing. Same CRON_SECRET auth + fail-closed-on-Vercel
    posture as /api/cron/crm-sync. Batched so a backlog can't exceed the
    function time budget. No-op (and cheap) when memory.formation_enabled is off.
    """
    if settings.cron_secret:
        bearer = (authorization or "")
        if bearer.startswith("Bearer "):
            bearer = bearer[len("Bearer "):].strip()
        if not (_secret_eq(bearer, settings.cron_secret)
                or _secret_eq(x_cron_secret, settings.cron_secret)):
            raise HTTPException(status_code=401, detail="Invalid cron secret.")
    elif os.environ.get("VERCEL"):
        logger.error("[cron] CRON_SECRET not set — memory-sweep disabled in production.")
        raise HTTPException(status_code=503, detail="Cron endpoint not configured.")

    if not _memory_formation_on():
        return {"status": "skipped", "reason": "formation disabled"}

    try:
        stats = nexus_memory.formation_sweep(
            call_llm=_call_llm,
            parse_json=_parse_llm_json,
            is_crisis_fn=is_crisis,
            model_version="gemini-2.5-flash",
        )
        _audit("memory_sweep", **stats)
        return {"status": "ok", **stats}
    except Exception as e:
        logger.error(f"[memory] sweep failed: {e}", exc_info=True)
        return {"status": "error", "detail": "sweep failed"}


@app.post("/api/raw_query", dependencies=[Depends(require_auth)])
def raw_query(request: RawQueryRequest, http_request: Request):
    """
    Execute raw SQL directly — bypasses the LLM entirely.
    Used by the SQL Editor mode in the frontend.
    Only SELECT/WITH queries are permitted (same validation as the chat pipeline).
    """
    client_ip = get_client_ip(http_request)
    sql       = request.sql.strip()

    if not sql:
        return {"status": "error", "reply": "No SQL provided.",
                "error_code": "validation_error"}

    # Apply rate limiting to raw queries as well
    try:
        check_rate_limit(client_ip)
    except RateLimitError:
        return {"status": "error",
                "reply": "Too many requests — please wait a moment.",
                "error_code": "rate_limit_error"}

    # Validate SQL (SELECT/WITH only, no dangerous keywords)
    try:
        validated_sql = validate_sql(sql)
    except SQLValidationError as e:
        logger.warning(f"[raw_query] Validation blocked from {client_ip!r}: {e}")
        return {"status": "error", "reply": f"SQL validation failed: {e}",
                "error_code": "validation_error"}

    try:
        with get_db_conn() as conn:
            t0 = time.perf_counter()
            rows, columns = execute_query(conn, validated_sql)
            execution_ms  = int((time.perf_counter() - t0) * 1000)

        logger.info(f"[raw_query] {client_ip!r}: {len(rows)} rows in {execution_ms}ms")
        _audit("raw_query", ip=client_ip, sql=sql[:120],
               row_count=len(rows), ms=execution_ms)

        n = len(rows)
        return {
            "status":       "success",
            "reply":        f"Query returned {n} row{'s' if n != 1 else ''}.",
            "columns":      columns,
            "raw_results":  [[_serialize_val(v) for v in row] for row in rows],
            "row_count":    n,
            "execution_ms": execution_ms,
        }

    except HTTPException:
        # Fail-closed signals (e.g. nexus_reader role unavailable) must surface
        # as a real HTTP error, not be downgraded to a 200 JSON error body.
        raise

    except psycopg2.Error as e:
        logger.error(f"[raw_query] PostgreSQL error: {e}")
        # Authenticated SQL editor needs error feedback, but surface ONLY the
        # primary Postgres message line (truncated) — never the full driver
        # context, query echo, position, or internal hints.
        pg_msg = (getattr(getattr(e, "diag", None), "message_primary", None)
                  or "Query failed").strip()
        return {"status": "error", "reply": f"SQL error: {pg_msg[:200]}",
                "error_code": "db_error"}

    except Exception as e:
        logger.error(f"[raw_query] Unexpected {type(e).__name__}: {e}", exc_info=True)
        return {"status": "error", "reply": "Query execution failed.",
                "error_code": "unknown"}
