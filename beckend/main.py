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
import threading
import decimal
import datetime
import uuid
import urllib.request
import concurrent.futures
from collections import OrderedDict
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

import psycopg2
import psycopg2.pool
from google import genai
from google.genai import types as genai_types
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


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

    model_config = {"env_file": ".env"}

settings = Settings()


# ─── Auth ─────────────────────────────────────────────────────────────────────

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
    if credentials is None or credentials.credentials != settings.nexus_api_key:
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


# ─── Schema Cache ─────────────────────────────────────────────────────────────

_schema_cache: str = ""   # populated once on first chat request; never changes at runtime

# Tables that exist for infrastructure / identity management — never exposed to
# the LLM so it cannot generate SELECT queries against internal session data.
_INTERNAL_TABLES = {"sessions", "messages", "knowledge_base", "app_config", "leads"}

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

_BLOCKED_TERMS = re.compile(
    r"\b(porn|sex(?:ual)?|nude|naked|xxx|fuck|shit|cunt|nigger|faggot"
    r"|kill\s+(?:me|yourself|him|her|them)|bomb(?:ing)?"
    r"|terrorist|suicide|self[_\-]harm|malware|ransomware)\b",
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

    psycopg2 connections are thread-safe; no global lock is needed because
    each request gets its own connection from the pool.
    """
    safe_sql = f"SELECT * FROM ({sql}) AS _q LIMIT {settings.max_result_rows}"
    with conn.cursor() as cur:
        cur.execute(safe_sql)
        columns = [desc[0] for desc in cur.description]
        rows    = cur.fetchall()
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

    logger.info(f"[pipeline] Question: {question!r}")
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
    history:    list[HistoryMessage] = []  # in-memory history (backward-compat)
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
    channel:    str = Field(default="web", pattern="^(web|whatsapp|telegram)$")
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
        logger.error(f"[db-test] Connection failed: {e}")
        return {
            "status":  "error",
            "detail":  str(e),
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
    logger.info(f"[chat] {client_ip!r} session={session_id!r}: {question!r}")
    _audit("chat_request", ip=client_ip, question=question, session_id=session_id)

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
        logger.warning(f"[chat] SQL validation blocked: {e}")
        _audit("sql_error", ip=client_ip, detail=str(e))
        return ChatResponse(
            status="error",
            reply="I generated a query that isn't allowed for safety reasons. Try rephrasing.",
            error_code="validation_error",
            sql_used=str(e),
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
def get_session_history(session_id: str):
    """
    Load the full message history for a session.

    Used by the frontend on page-load to restore a previous conversation from
    localStorage — the frontend supplies the stored session_id and receives
    back all turns so the chat UI can be reconstructed exactly.
    """
    try:
        with get_db_conn() as conn:
            # Verify the session exists before loading messages.
            with conn.cursor() as cur:
                cur.execute("SELECT channel FROM sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found.")
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

    _audit("rag_request", ip=client_ip, question=question)

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

# Booking-intent detector — triggers the native contact-share keyboard after
# the RAG reply so the steering feels conversational, not pushy.
_BOOKING_INTENT = re.compile(
    r"(פגישה|ייעוץ|לקבוע|להירשם|להתייעץ|הרשמה|קביעת\s*תור|שיחה\s*אישית|"
    r"לדבר\s*עם\s*ארז|ליצור\s*קשר|לפגוש|תור\b|מחיר|כמה\s*עולה|"
    r"book|booking|appointment|consultation|session|schedule|sign\s*up|contact)",
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

def _is_escape_intent(text: str) -> bool:
    """True when the message is a clear opt-out from the current funnel step."""
    return bool(_ESCAPE_INTENT.search(text or ""))


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


def _format_lead_thanks(name: str | None) -> str:
    """
    Build the lead confirmation message without a double-space when no name is given.
    `_TG_LEAD_THANKS.format(name='')` produces 'תודה  🙏' (double space); this
    helper inserts 'name + space' only when a non-empty name is available.
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
_TG_LEAD_THANKS = "תודה {name} 🙏 הפנייה התקבלה וארז יחזור אליכם בהקדם. בינתיים, אם יש עוד שאלות — אני כאן."
_TG_LEAD_DUPLICATE = None   # silent — we already have this person's number; don't re-ask


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


def _db_has_lead(conn, chat_id_str: str) -> bool:
    """True if we already captured a lead from this Telegram user (by chat_id)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM leads WHERE channel = 'telegram' AND chat_id = %s LIMIT 1",
            (chat_id_str,),
        )
        return cur.fetchone() is not None


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
            VALUES (%s, %s, 'telegram', %s, %s, %s)
            ON CONFLICT (channel, chat_id) DO NOTHING
            RETURNING id
            """,
            (session_id, chat_id, name or None, phone, intent_summary or None),
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


def _alert_owner(lead_id: str, name: str, phone: str, intent_summary: str, chat_id: str) -> None:
    """
    DM Erez on Telegram with the structured lead details. Best-effort — a
    delivery failure is logged but never propagated; the user's confirmation
    has already been sent and must not be affected.
    """
    if not settings.telegram_owner_chat_id:
        logger.warning("[leads] TELEGRAM_OWNER_CHAT_ID not set — owner alert skipped.")
        return

    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")
    name_str   = name or "לא צוין"
    intent_str = intent_summary or "—"

    text = (
        f"🔔 ליד חדש מהבוט\n\n"
        f"👤 שם: {name_str}\n"
        f"📱 טלפון: {phone}\n"
        f"💬 נושא: {intent_str}\n"
        f"🕐 {now_str}\n\n"
        f"לפתיחת השיחה: tg://user?id={chat_id}"
    )
    _send_telegram_message(settings.telegram_owner_chat_id, text)
    logger.info(f"[leads] Owner alerted for lead {lead_id}")


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
    """
    Map a Telegram chat_id to a persistent Nexus session, reusing the existing
    sessions table (channel='telegram', contact_id=chat_id). A returning user
    therefore keeps their full conversation memory across messages and redeploys.

    Race-safe: relies on the UNIQUE(channel, contact_id) index — if two first
    messages arrive at once, the second INSERT is a no-op (ON CONFLICT) and we
    re-select the row the winner created. Caller owns the commit.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM sessions WHERE channel = 'telegram' AND contact_id = %s LIMIT 1",
            (chat_id,),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])

        cur.execute(
            """
            INSERT INTO sessions (channel, contact_id)
            VALUES ('telegram', %s)
            ON CONFLICT (channel, contact_id) DO NOTHING
            RETURNING id
            """,
            (chat_id,),
        )
        inserted = cur.fetchone()
        if inserted:
            return str(inserted[0])

        # A concurrent request won the insert — re-select its row.
        cur.execute(
            "SELECT id FROM sessions WHERE channel = 'telegram' AND contact_id = %s LIMIT 1",
            (chat_id,),
        )
        return str(cur.fetchone()[0])


def _send_telegram_message(chat_id, text: str, reply_markup: dict = None) -> None:
    """
    Deliver a reply via Telegram's sendMessage. Uses the stdlib urllib so no HTTP
    dependency is added to the serverless bundle. Best-effort: any network error
    is logged, never raised — the webhook must always return 200 or Telegram will
    retry the update and the user gets duplicate replies.

    reply_markup: optional Telegram ReplyKeyboardMarkup / ReplyKeyboardRemove dict.
    Pass {"keyboard": [[{"text": "…", "request_contact": true}]], …} to show a
    contact-share button, or {"remove_keyboard": true} to dismiss it.
    """
    if not settings.telegram_bot_token:
        logger.error("[telegram] TELEGRAM_BOT_TOKEN not set — cannot send reply.")
        return

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
            resp.read()
    except Exception as e:
        logger.error(f"[telegram] sendMessage to {chat_id} failed: {e}")


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
        f"{preamble}\n\n{_TG_CONTACT_PROMPT}",
        reply_markup=_CONTACT_KEYBOARD,
    )


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
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
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

                if lead_id:
                    # Alert the owner (best-effort, non-blocking)
                    _alert_owner(lead_id, name, phone, intent_summary, chat_id_str)
                    with get_db_conn() as conn:
                        _db_mark_lead_notified(conn, lead_id)
                        conn.commit()
                    _audit("lead_captured", chat_id=chat_id_str,
                           lead_id=lead_id, phone_len=len(phone))
                else:
                    logger.info(f"[leads] Duplicate contact from {chat_id_str} — skipped.")

                # Warm confirmation + remove the keyboard regardless of dedup
                _send_telegram_message(chat_id, _format_lead_thanks(name),
                                       reply_markup=_REMOVE_KEYBOARD)
            except Exception as e:
                logger.error(f"[leads] Contact capture failed: {e}", exc_info=True)
                _send_telegram_message(chat_id, _TG_ERROR,
                                       reply_markup=_REMOVE_KEYBOARD)
        return {"ok": True}

    # ── 2b. Parse text ────────────────────────────────────────────────────────
    text = (message.get("text") or "").strip()

    if not text:
        _send_telegram_message(chat_id, _TG_NON_TEXT)   # sticker / photo / voice
        return {"ok": True}
    if text.startswith("/start"):
        _send_telegram_message(chat_id, _get_config("telegram.greeting"))
        return {"ok": True}

    # ── Crisis check — always first among text handlers ───────────────────────
    # The empathetic response is delivered BEFORE any DB work so that a DB
    # hiccup can never block it. State is then cleared so the user returns to
    # a clean conversation after speaking with a professional — not the contact
    # keyboard or the qualification question.
    if is_crisis(text):
        _audit("telegram_crisis", chat_id=chat_id_str)
        _send_telegram_message(chat_id, _get_config("crisis.message"))
        try:
            with get_db_conn() as conn:
                sid = _db_get_or_create_telegram_session(conn, chat_id_str)
                if _db_get_session_state(conn, sid):   # only write if there's state to clear
                    _db_set_session_state(conn, sid, None)
                    conn.commit()
        except Exception:
            pass   # non-critical — never let this block or delay the crisis response
        return {"ok": True}

    _audit("telegram_request", chat_id=chat_id_str, question=text)

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

        # ── Escape-intent gate ────────────────────────────────────────────────────
        # Runs BEFORE validate_question and all state checks.
        # If a user in any funnel state sends an opt-out signal ("לא", "בטל",
        # "cancel"…) we clear state gracefully and let them ask freely.
        # Short signals like "לא" (2 chars) would fail the length guard if we
        # checked escape intent after validate_question — so we check here.
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
                        _alert_owner(lead_id, None, phone, intent_summary, chat_id_str)
                        with get_db_conn() as conn:
                            _db_mark_lead_notified(conn, lead_id)
                            conn.commit()
                        _audit("lead_captured_regex_awaiting", chat_id=chat_id_str,
                               lead_id=lead_id)
                        _send_telegram_message(chat_id, _format_lead_thanks(None),
                                               reply_markup=_REMOVE_KEYBOARD)
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
        if len(text) > 500:
            _send_telegram_message(chat_id, _TG_TOO_LONG)
            return {"ok": True}
        try:
            validate_question(text)
        except InputModerationError:
            _audit("telegram_moderation_block", chat_id=chat_id_str)
            _send_telegram_message(chat_id, _TG_MODERATION)
            return {"ok": True}

        # ── PATH A: qualification answer ──────────────────────────────────────
        # User replied to "what would you like to talk about?".
        # Skip the LLM: acknowledge warmly, show the contact keyboard, advance
        # state to awaiting_contact:0 (retry counter starts at zero).
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
            else:
                with get_db_conn() as conn:
                    _db_set_session_state(conn, session_id, None)
                    conn.commit()
            if not already_lead:
                return {"ok": True}

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
                    _alert_owner(lead_id, None, phone_in_text, intent_summary, chat_id_str)
                    with get_db_conn() as conn:
                        _db_mark_lead_notified(conn, lead_id)
                        conn.commit()
                    _audit("lead_captured_regex", chat_id=chat_id_str, lead_id=lead_id)
                    _send_telegram_message(chat_id, _format_lead_thanks(None))
                    return {"ok": True}
            except Exception as e:
                logger.error(f"[leads] Regex capture failed: {e}", exc_info=True)

        # ── PATH B / C: normal RAG + optional qualification trigger ───────────
        # Embedding is the slowest step — only reached here (not for PATH A or
        # awaiting_contact, which return early with scripted responses).
        query_vector = _embed_text(text)
        with get_db_conn() as conn:
            chunks = _retrieve_chunks(conn, query_vector, top_k=5)

        reply, sources = _rag_generate(text, chunks, history=history)

        trigger_qualification = (
            _has_booking_intent(text)
            and not already_lead
            and bot_state is None
        )

        with get_db_conn() as conn:
            _db_save_message(conn, session_id, "user", text)
            _db_save_message(conn, session_id, "assistant", reply)
            if trigger_qualification:
                _db_set_session_state(conn, session_id, "awaiting_qualification")
            _db_touch_session(conn, session_id)
            conn.commit()

        _audit("telegram_success", chat_id=chat_id_str, session_id=session_id,
               sources=sources, chunks=len(chunks),
               qualification_triggered=trigger_qualification)

        _send_telegram_message(chat_id, reply)
        if trigger_qualification:
            _send_telegram_message(chat_id, _TG_QUALIFICATION_QUESTION)

    except TimeoutError:
        logger.error("[telegram] LLM timeout")
        _send_telegram_message(chat_id, _TG_TIMEOUT)
    except Exception as e:
        logger.error(f"[telegram] Unexpected {type(e).__name__}: {e}", exc_info=True)
        _send_telegram_message(chat_id, _TG_ERROR)

    return {"ok": True}


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

    except psycopg2.Error as e:
        logger.error(f"[raw_query] PostgreSQL error: {e}")
        return {"status": "error", "reply": f"SQL error: {e}",
                "error_code": "db_error"}

    except Exception as e:
        logger.error(f"[raw_query] Unexpected {type(e).__name__}: {e}", exc_info=True)
        return {"status": "error", "reply": "Query execution failed.",
                "error_code": "unknown"}
