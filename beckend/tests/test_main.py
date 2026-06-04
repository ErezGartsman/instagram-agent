"""
DataLens Backend — Unit Tests
==============================
All external I/O (PostgreSQL, Gemini) is mocked so these tests run in CI
with no credentials and no network access.

Test categories:
  1. SQL Validation  — pure logic, no mocks needed
  2. Input Moderation — pure logic, no mocks needed
  3. /health          — mocked DB
  4. /db-test         — mocked DB
  5. /api/stats       — mocked DB
  6. /api/raw_query   — mocked DB + validation paths
  7. /api/chat        — mocked DB + mocked LLM
  8. Serialisation    — pure logic
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

# ── Import the app ──────────────────────────────────────────────────────────
# We patch _get_pool at import time so no real DB connection is attempted
# during TestClient construction (which triggers lifespan).
import main
from main import app, validate_sql, validate_question, _serialize_val, SQLValidationError, InputModerationError


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_mock_conn(fetchone_return=None, fetchall_return=None, description=None):
    """
    Build a mock psycopg2 connection whose cursor context manager returns
    pre-canned results.  All tests that touch a DB path use this.
    """
    mock_cursor = MagicMock()
    # Default two-column row: satisfies _db_get_session_state's (bot_state, expires_at)
    # unpack without erroring, while returning None state (no funnel active).
    mock_cursor.fetchone.return_value  = fetchone_return or (None, None)
    mock_cursor.fetchall.return_value  = fetchall_return or []
    mock_cursor.description            = description or [("col",)]

    # Make the cursor work as a context manager  (`with conn.cursor() as cur:`)
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__  = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def client():
    """
    FastAPI TestClient with the pool and schema cache reset between tests.
    The pool is patched so it never dials Supabase.
    """
    # Reset module-level caches so tests don't bleed into each other
    main._schema_cache    = ""
    main._pool            = None
    main._config_cache    = {}
    main._config_cache_ts = 0.0
    # Default the Telegram secret OFF so webhook tests don't depend on whether a
    # real TELEGRAM_WEBHOOK_SECRET happens to be set in the local .env. Tests that
    # exercise the secret gate set it explicitly via monkeypatch.
    main.settings.telegram_webhook_secret = ""
    # Rate store is module-level and accumulates across tests.  Moving
    # check_rate_limit before the DB checkout means more paths now hit it;
    # clear it here so no test bleeds its request count into the next one.
    main._rate_store.clear()

    with patch.object(main, "_get_pool") as mock_get_pool:
        mock_pool = MagicMock()
        mock_get_pool.return_value = mock_pool

        # Default: each getconn() returns a fresh mock connection
        mock_conn, _ = _make_mock_conn()
        mock_pool.getconn.return_value = mock_conn

        with TestClient(app, raise_server_exceptions=True) as c:
            c._mock_pool = mock_pool   # expose so individual tests can reconfigure
            yield c


def _patch_conn(client, fetchone=None, fetchall=None, description=None):
    """Helper: reconfigure the mock pool's connection mid-test."""
    mock_conn, mock_cursor = _make_mock_conn(fetchone, fetchall, description)
    client._mock_pool.getconn.return_value = mock_conn
    return mock_conn, mock_cursor


# ─── 1. SQL Validation ────────────────────────────────────────────────────────

class TestValidateSql:
    def test_plain_select_passes(self):
        sql = validate_sql("SELECT * FROM posts")
        assert sql == "SELECT * FROM posts"

    def test_with_cte_passes(self):
        sql = validate_sql("WITH t AS (SELECT 1) SELECT * FROM t")
        assert "WITH" in sql

    def test_trailing_semicolon_stripped(self):
        sql = validate_sql("SELECT 1;")
        assert not sql.endswith(";")

    def test_drop_blocked(self):
        # Caught by layer 1 (non-SELECT start) — still raises SQLValidationError
        with pytest.raises(SQLValidationError):
            validate_sql("DROP TABLE posts")

    def test_delete_blocked(self):
        with pytest.raises(SQLValidationError):
            validate_sql("DELETE FROM posts")

    def test_insert_blocked(self):
        with pytest.raises(SQLValidationError):
            validate_sql("INSERT INTO posts VALUES (1)")

    def test_update_blocked(self):
        with pytest.raises(SQLValidationError):
            validate_sql("UPDATE posts SET x = 1")

    def test_create_blocked(self):
        with pytest.raises(SQLValidationError):
            validate_sql("CREATE TABLE evil (x INT)")

    def test_truncate_blocked(self):
        with pytest.raises(SQLValidationError):
            validate_sql("TRUNCATE posts")

    def test_pg_read_file_blocked(self):
        with pytest.raises(SQLValidationError, match="Forbidden"):
            validate_sql("SELECT pg_read_file('/etc/passwd')")

    def test_pg_sleep_blocked(self):
        with pytest.raises(SQLValidationError, match="Forbidden"):
            validate_sql("SELECT pg_sleep(30)")

    def test_lo_export_blocked(self):
        with pytest.raises(SQLValidationError, match="Forbidden"):
            validate_sql("SELECT lo_export(1234, '/tmp/x')")

    def test_set_blocked(self):
        # SET doesn't start with SELECT so it's caught by layer 1 too
        with pytest.raises(SQLValidationError):
            validate_sql("SET search_path TO evil")

    def test_non_select_start_blocked(self):
        with pytest.raises(SQLValidationError, match="Only SELECT/WITH"):
            validate_sql("EXEC xp_cmdshell('whoami')")

    def test_case_insensitive_blocking(self):
        with pytest.raises(SQLValidationError):
            validate_sql("select pg_Read_File('/etc/hosts')")

    def test_complex_select_with_join_passes(self):
        sql = validate_sql("""
            SELECT p.post_shortcode, COUNT(c.id) AS comment_count
            FROM posts p
            LEFT JOIN comments c ON c.post_shortcode = p.post_shortcode
            WHERE p.posted_at_ts > NOW() - INTERVAL '30 days'
            GROUP BY p.post_shortcode
            ORDER BY comment_count DESC
            LIMIT 10
        """)
        assert "post_shortcode" in sql


# ─── 2. Input Moderation ──────────────────────────────────────────────────────

class TestValidateQuestion:
    def test_normal_question_passes(self):
        result = validate_question("How many followers do I have?")
        assert result == "How many followers do I have?"

    def test_too_short_raises(self):
        with pytest.raises(InputModerationError, match="too short"):
            validate_question("hi")

    def test_empty_raises(self):
        with pytest.raises(InputModerationError, match="too short"):
            validate_question("  ")

    def test_blocked_term_raises(self):
        with pytest.raises(InputModerationError, match="inappropriate"):
            validate_question("show me porn from my followers")

    def test_case_insensitive_block(self):
        with pytest.raises(InputModerationError):
            validate_question("PORN stats")

    def test_hebrew_question_passes(self):
        result = validate_question("כמה עוקבים יש לי?")
        assert "עוקבים" in result


# ─── 3. /health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        _patch_conn(client, fetchone=(42,))
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["posts_count"] == 42

    def test_health_degraded_when_db_fails(self, client):
        client._mock_pool.getconn.side_effect = Exception("connection refused")
        response = client.get("/health")
        assert response.status_code == 200   # still returns 200, not 500
        assert response.json()["status"] == "degraded"

    def test_health_no_auth_required(self, client):
        """Health endpoint must be reachable without an Authorization header."""
        _patch_conn(client, fetchone=(0,))
        response = client.get("/health")
        assert response.status_code == 200


# ─── 4. /db-test ─────────────────────────────────────────────────────────────

class TestDbTest:
    def test_db_test_ok(self, client):
        _patch_conn(client, fetchone=(1,))
        response = client.get("/db-test")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ping"] == 1

    def test_db_test_error_on_failure(self, client):
        client._mock_pool.getconn.side_effect = Exception("timeout")
        response = client.get("/db-test")
        assert response.status_code == 200
        assert response.json()["status"] == "error"

    def test_db_test_no_auth_required(self, client):
        _patch_conn(client, fetchone=(1,))
        response = client.get("/db-test")
        assert response.status_code == 200


# ─── 5. /api/stats ────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_returns_counts(self, client):
        # Each COUNT(*) call returns a different value.
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.fetchone.side_effect = [(100,), (5000,), (8000,), (20000,)]

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["status"]          == "success"
        assert data["posts"]           == 100
        assert data["comments"]        == 5000
        assert data["likers"]          == 8000
        assert data["total_followers"] == 20000

    def test_stats_error_on_db_failure(self, client):
        client._mock_pool.getconn.side_effect = Exception("pool exhausted")
        response = client.get("/api/stats")
        assert response.status_code == 200
        assert response.json()["status"] == "error"


# ─── 6. /api/raw_query ────────────────────────────────────────────────────────

class TestRawQuery:
    def _post(self, client, sql: str):
        return client.post("/api/raw_query", json={"sql": sql})

    # ── Validation paths (no DB touch) ───────────────────────────────────────
    def test_drop_is_blocked(self, client):
        r = self._post(client, "DROP TABLE posts")
        assert r.json()["error_code"] == "validation_error"

    def test_pg_read_file_is_blocked(self, client):
        r = self._post(client, "SELECT pg_read_file('/etc/passwd')")
        assert r.json()["error_code"] == "validation_error"

    def test_empty_sql_blocked(self, client):
        r = self._post(client, "   ")
        assert r.json()["error_code"] == "validation_error"

    def test_sql_exceeding_max_length_rejected(self, client):
        r = self._post(client, "SELECT 1" + " " * 8_001)
        # pydantic Field(max_length=8000) returns 422 Unprocessable Entity
        assert r.status_code == 422

    # ── Successful execution path ─────────────────────────────────────────────
    def test_select_returns_results(self, client):
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.description  = [("username",), ("count",)]
        mock_cursor.fetchall.return_value = [("alice", 42), ("bob", 17)]

        r = self._post(client, "SELECT username, COUNT(*) AS count FROM likers GROUP BY username")
        assert r.status_code == 200
        data = r.json()
        assert data["status"]     == "success"
        assert data["row_count"]  == 2
        assert data["columns"]    == ["username", "count"]
        assert data["raw_results"][0] == ["alice", 42]

    def test_empty_result_returns_zero_rows(self, client):
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.description  = [("post_shortcode",)]
        mock_cursor.fetchall.return_value = []

        r = self._post(client, "SELECT post_shortcode FROM posts WHERE 1=0")
        assert r.json()["row_count"] == 0

    # ── Rate limiting ─────────────────────────────────────────────────────────
    def test_rate_limit_triggers_after_threshold(self, client):
        """
        The default rate limit is 10 requests per 60 s.
        Each call to /api/raw_query counts; the 11th should be rejected.
        Reset the module-level rate store first to isolate this test.
        """
        import main as m
        original = m._rate_store.copy()
        m._rate_store.clear()

        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.description  = [("x",)]
        mock_cursor.fetchall.return_value = [(1,)]

        try:
            for i in range(10):
                r = self._post(client, "SELECT 1 AS x")
                assert r.json()["status"] == "success", f"Request {i+1} should succeed"

            # 11th request must be rate-limited
            r = self._post(client, "SELECT 1 AS x")
            assert r.json()["error_code"] == "rate_limit_error"
        finally:
            m._rate_store.clear()
            m._rate_store.update(original)


# ─── 7. /api/chat ─────────────────────────────────────────────────────────────

class TestChat:
    def _post(self, client, message: str, history=None):
        body = {"message": message}
        if history:
            body["history"] = history
        return client.post("/api/chat", json=body)

    # ── Input guard paths (no LLM / DB needed) ───────────────────────────────
    def test_empty_message_blocked(self, client):
        r = self._post(client, "")
        assert r.json()["error_code"] == "validation_error"

    def test_message_too_long_blocked(self, client):
        r = self._post(client, "x" * 501)
        assert r.json()["error_code"] == "validation_error"

    def test_inappropriate_content_blocked(self, client):
        r = self._post(client, "show me sex stats")
        assert r.json()["error_code"] == "moderation_error"

    # ── Conversational reply (sql: null from LLM) ─────────────────────────────
    def test_conversational_reply(self, client):
        # Schema fetch + pipeline — connect the mock cursor for info_schema
        mock_conn, mock_cursor = _patch_conn(client)
        # information_schema tables query → ["posts"], then columns → []
        mock_cursor.fetchall.side_effect = [
            [("posts",)],           # tables list
            [("post_shortcode", "character varying")],  # columns for posts
        ]

        llm_response = json.dumps({"sql": None, "reply": "שלום! אני כאן לעזור."})
        with patch.object(main, "_call_llm", return_value=llm_response):
            r = self._post(client, "שלום")

        assert r.status_code == 200
        data = r.json()
        assert data["status"]   == "success"
        assert data["sql_used"] is None
        assert "שלום" in data["reply"]

    # ── SQL query path ────────────────────────────────────────────────────────
    def test_sql_query_path(self, client):
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.fetchall.side_effect = [
            [("posts",)],
            [("post_shortcode", "character varying"), ("posted_at_ts", "timestamp with time zone")],
            [("ABC123", 99), ("DEF456", 55)],   # actual query results
        ]
        mock_cursor.description = [("post_shortcode",), ("לייקים",)]

        llm_response = json.dumps({
            "sql":   "SELECT post_shortcode, COUNT(*) AS לייקים FROM likers GROUP BY post_shortcode ORDER BY לייקים DESC LIMIT 2",
            "reply": "הפוסטים עם הכי הרבה לייקים:",
        })

        with patch.object(main, "_call_llm", return_value=llm_response):
            r = self._post(client, "אילו פוסטים קיבלו הכי הרבה לייקים?")

        assert r.status_code == 200
        data = r.json()
        assert data["status"]    == "success"
        assert data["sql_used"]  is not None
        assert data["row_count"] == 2

    # ── LLM timeout ───────────────────────────────────────────────────────────
    def test_llm_timeout_returns_error(self, client):
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.fetchall.side_effect = [
            [("posts",)],
            [("post_shortcode", "character varying")],
        ]

        with patch.object(main, "_call_llm", side_effect=TimeoutError("LLM timeout")):
            r = self._post(client, "כמה עוקבים?")

        assert r.json()["error_code"] == "llm_error"

    # ── SQL validation blocks dangerous LLM output ───────────────────────────
    def test_dangerous_llm_sql_blocked(self, client):
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.fetchall.side_effect = [
            [("posts",)],
            [("post_shortcode", "character varying")],
        ]

        # Simulate a prompt-injected LLM response that tries to drop a table
        llm_response = json.dumps({
            "sql":   "DROP TABLE posts",
            "reply": "מוחק...",
        })

        with patch.object(main, "_call_llm", return_value=llm_response):
            r = self._post(client, "מחק את הטבלה")

        assert r.json()["error_code"] == "validation_error"


# ─── 8. Serialisation ─────────────────────────────────────────────────────────

class TestSerializeVal:
    import datetime, decimal, uuid as _uuid

    def test_none(self):       assert _serialize_val(None)  is None
    def test_bool(self):       assert _serialize_val(True)  is True
    def test_int(self):        assert _serialize_val(42)    == 42
    def test_float(self):      assert _serialize_val(3.14)  == 3.14
    def test_str(self):        assert _serialize_val("hi")  == "hi"

    def test_decimal(self):
        import decimal
        assert _serialize_val(decimal.Decimal("9.99")) == pytest.approx(9.99)

    def test_datetime(self):
        import datetime
        dt  = datetime.datetime(2024, 1, 15, 12, 0, 0)
        res = _serialize_val(dt)
        assert isinstance(res, str)
        assert "2024" in res

    def test_date(self):
        import datetime
        d   = datetime.date(2024, 6, 1)
        res = _serialize_val(d)
        assert isinstance(res, str)
        assert "2024" in res

    def test_uuid(self):
        import uuid
        u   = uuid.uuid4()
        res = _serialize_val(u)
        assert isinstance(res, str)
        assert len(res) == 36   # standard UUID string length


# ─── 9. Telegram chat_id → session_id mapping (pure logic, mocked cursor) ──────

class TestTelegramSessionMapping:
    def test_returning_user_reuses_session(self):
        """An existing telegram session is returned without any INSERT."""
        mock_conn, mock_cursor = _make_mock_conn()
        mock_cursor.fetchone.return_value = ("sess-existing",)

        sid = main._db_get_or_create_telegram_session(mock_conn, "12345")

        assert sid == "sess-existing"
        # Only the SELECT ran — no INSERT for a known user.
        assert mock_cursor.execute.call_count == 1

    def test_new_user_creates_session(self):
        """First-ever message: SELECT misses, INSERT ... RETURNING creates the row."""
        mock_conn, mock_cursor = _make_mock_conn()
        mock_cursor.fetchone.side_effect = [None, ("sess-new",)]

        sid = main._db_get_or_create_telegram_session(mock_conn, "999")

        assert sid == "sess-new"
        assert mock_cursor.execute.call_count == 2   # SELECT then INSERT

    def test_insert_race_falls_back_to_reselect(self):
        """If a concurrent insert wins (ON CONFLICT → no row), we re-select it."""
        mock_conn, mock_cursor = _make_mock_conn()
        # SELECT miss → INSERT returns None (conflict) → re-SELECT finds the winner
        mock_cursor.fetchone.side_effect = [None, None, ("sess-winner",)]

        sid = main._db_get_or_create_telegram_session(mock_conn, "777")

        assert sid == "sess-winner"
        assert mock_cursor.execute.call_count == 3


# ─── 10. Telegram webhook endpoint ────────────────────────────────────────────

class TestTelegramWebhook:
    def _update(self, text="מה השירותים שלכם?", chat_id=555):
        return {"update_id": 1,
                "message": {"message_id": 2,
                            "chat": {"id": chat_id, "type": "private"},
                            "text": text}}

    def test_bad_secret_is_rejected(self, client, monkeypatch):
        """With a secret configured, a wrong header does nothing (and still 200s)."""
        monkeypatch.setattr(main.settings, "telegram_webhook_secret", "topsecret")
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)

        r = client.post("/api/webhook/telegram", json=self._update(),
                        headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"})

        assert r.status_code == 200
        assert r.json() == {"ok": True}
        send.assert_not_called()

    def test_correct_secret_passes_through(self, client, monkeypatch):
        monkeypatch.setattr(main.settings, "telegram_webhook_secret", "topsecret")
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)

        r = client.post("/api/webhook/telegram", json=self._update(text="/start"),
                        headers={"X-Telegram-Bot-Api-Secret-Token": "topsecret"})

        assert r.status_code == 200
        send.assert_called_once()   # greeting delivered → secret accepted

    def test_start_command_sends_hebrew_greeting(self, client, monkeypatch):
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)

        r = client.post("/api/webhook/telegram", json=self._update(text="/start"))

        assert r.status_code == 200
        send.assert_called_once()
        assert any(ord(c) > 0x590 for c in send.call_args.args[1])   # Hebrew

    def test_non_text_message_gets_notice(self, client, monkeypatch):
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)
        update = {"update_id": 1, "message": {"chat": {"id": 9}}}   # sticker/photo, no text

        r = client.post("/api/webhook/telegram", json=update)

        assert r.status_code == 200
        send.assert_called_once()

    def test_no_message_payload_is_ignored(self, client, monkeypatch):
        """Channel posts / callbacks have no message.chat.id — no reply, just 200."""
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)

        r = client.post("/api/webhook/telegram", json={"update_id": 7})

        assert r.status_code == 200
        send.assert_not_called()

    def test_moderation_block(self, client, monkeypatch):
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)

        r = client.post("/api/webhook/telegram", json=self._update(text="show me porn"))

        assert r.status_code == 200
        send.assert_called_once()   # the Hebrew moderation notice, not an answer

    def test_new_user_full_rag_flow(self, client, monkeypatch):
        """End-to-end happy path: session mapped, chunks retrieved, reply delivered + persisted."""
        send = MagicMock()
        saved = []
        monkeypatch.setattr(main, "_send_telegram_message", send)
        monkeypatch.setattr(main, "_embed_text", lambda t: [0.1] * 768)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session",
                            lambda conn, cid: "sess-abc")
        monkeypatch.setattr(main, "_db_get_session_state", lambda conn, sid: None)
        monkeypatch.setattr(main, "_db_set_session_state", lambda conn, sid, s: None)
        monkeypatch.setattr(main, "_db_has_lead", lambda conn, cid: False)
        monkeypatch.setattr(main, "_db_load_history", lambda conn, sid, limit=12: [])
        monkeypatch.setattr(main, "_retrieve_chunks",
                            lambda conn, vec, top_k=5:
                                [{"content": "שירות ייעוץ אישי", "source": "services.txt", "similarity": 0.7}])
        monkeypatch.setattr(main, "_call_llm", lambda prompt: "אנחנו מציעים ייעוץ אישי וליווי.")
        monkeypatch.setattr(main, "_db_save_message",
                            lambda conn, sid, role, content, **k: saved.append((role, content)))
        monkeypatch.setattr(main, "_db_touch_session", lambda conn, sid: None)

        r = client.post("/api/webhook/telegram", json=self._update())

        assert r.status_code == 200
        send.assert_called_once()
        assert send.call_args.args[1] == "אנחנו מציעים ייעוץ אישי וליווי."
        # both the user turn and the assistant turn were persisted
        assert [s[0] for s in saved] == ["user", "assistant"]

    def test_history_is_passed_into_prompt(self, client, monkeypatch):
        """Returning user: prior turns are loaded and fed to the RAG prompt (memory)."""
        captured = {}
        monkeypatch.setattr(main, "_send_telegram_message", MagicMock())
        monkeypatch.setattr(main, "_embed_text", lambda t: [0.1] * 768)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session",
                            lambda conn, cid: "sess-xyz")
        monkeypatch.setattr(main, "_db_get_session_state", lambda conn, sid: None)
        monkeypatch.setattr(main, "_db_set_session_state", lambda conn, sid, s: None)
        monkeypatch.setattr(main, "_db_has_lead", lambda conn, cid: False)
        monkeypatch.setattr(main, "_db_load_history", lambda conn, sid, limit=12:
                            [{"role": "user", "content": "מי זה ארז?"},
                             {"role": "assistant", "content": "ארז גרצמן הוא מנטור."}])
        monkeypatch.setattr(main, "_retrieve_chunks", lambda conn, vec, top_k=5:
                            [{"content": "מידע", "source": "about.txt", "similarity": 0.6}])
        monkeypatch.setattr(main, "_db_save_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_touch_session", lambda conn, sid: None)

        def _capture_llm(prompt):
            captured["prompt"] = prompt
            return "תשובה"
        monkeypatch.setattr(main, "_call_llm", _capture_llm)

        r = client.post("/api/webhook/telegram", json=self._update(text="ומה המחיר?"))

        assert r.status_code == 200
        # The previous turns appear in the prompt context block.
        assert "RECENT CONVERSATION" in captured["prompt"]
        assert "ארז גרצמן הוא מנטור" in captured["prompt"]

    def test_crisis_message_for_distress(self, client, monkeypatch):
        """Distress/self-harm → compassionate ERAN (1201) message, never the LLM."""
        send = MagicMock()
        llm  = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)
        monkeypatch.setattr(main, "_call_llm", llm)   # must NOT be reached

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני לא רוצה לחיות יותר, אין טעם"))

        assert r.status_code == 200
        send.assert_called_once()
        assert "1201" in send.call_args.args[1]   # ERAN hotline number
        llm.assert_not_called()

    def test_greeting_comes_from_config(self, client, monkeypatch):
        """/start delivers the config-driven greeting (default mentions Erez)."""
        send = MagicMock()
        monkeypatch.setattr(main, "_send_telegram_message", send)

        r = client.post("/api/webhook/telegram", json=self._update(text="/start"))

        assert r.status_code == 200
        assert "ארז גרצמן" in send.call_args.args[1]

    def _base_rag_patches(self, monkeypatch, *, already_lead=False, bot_state=None):
        """Shared monkeypatching for the RAG path — keeps individual tests concise."""
        monkeypatch.setattr(main, "_embed_text", lambda t: [0.1] * 768)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_get_session_state", lambda c, sid: bot_state)
        monkeypatch.setattr(main, "_db_set_session_state", lambda c, sid, s: None)
        monkeypatch.setattr(main, "_db_has_lead", lambda c, cid: already_lead)
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_retrieve_chunks", lambda c, v, top_k=5:
                            [{"content": "x", "source": "services.txt", "similarity": 0.7}])
        monkeypatch.setattr(main, "_call_llm", lambda p: "הנה מידע")
        monkeypatch.setattr(main, "_db_save_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_touch_session", lambda c, sid: None)

    def test_booking_intent_triggers_qualification_question(self, client, monkeypatch):
        """Booking intent + no lead → RAG reply then qualification question (no keyboard yet)."""
        messages_sent = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text, "markup": reply_markup}))
        self._base_rag_patches(monkeypatch, already_lead=False, bot_state=None)

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני מעוניין בפגישת ייעוץ"))

        assert r.status_code == 200
        assert len(messages_sent) == 2                        # RAG reply + qualification question
        assert messages_sent[1]["markup"] is None             # NO keyboard yet
        assert "נשמח לשמוע" in messages_sent[1]["text"]      # qualification question text

    def test_no_qualification_when_lead_already_exists(self, client, monkeypatch):
        """Booking intent + existing lead → single RAG reply, no qualification question."""
        messages_sent = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text}))
        self._base_rag_patches(monkeypatch, already_lead=True, bot_state=None)

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני מעוניין בפגישת ייעוץ"))

        assert r.status_code == 200
        assert len(messages_sent) == 1                        # RAG reply only

    def test_qualification_answer_sends_contact_keyboard(self, client, monkeypatch):
        """When state='awaiting_qualification' any user reply triggers the contact keyboard
        (via _send_contact_keyboard so UX instructions are always appended)."""
        messages_sent = []
        states_set    = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text, "markup": reply_markup}))
        self._base_rag_patches(monkeypatch, already_lead=False,
                               bot_state="awaiting_qualification")
        # Override the state-setter spy AFTER base patches so it isn't overwritten.
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: states_set.append(s))

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני עוברת גירושין ומתקשה להמשיך"))

        assert r.status_code == 200
        assert len(messages_sent) == 1                          # ack only, no LLM
        assert messages_sent[0]["markup"] is not None           # keyboard attached
        assert messages_sent[0]["markup"].get("keyboard") is not None
        assert "תודה על השיתוף" in messages_sent[0]["text"]    # new gender-neutral ACK
        assert "הכפתור הגדול" in messages_sent[0]["text"]      # UX instructions appended
        assert "awaiting_contact:0" in states_set                # state advanced to retry-0

    def test_awaiting_contact_non_phone_re_shows_keyboard(self, client, monkeypatch):
        """While awaiting_contact, typing 'כן' (or any non-phone text) re-shows the keyboard."""
        messages_sent = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text, "markup": reply_markup}))
        self._base_rag_patches(monkeypatch, already_lead=False,
                               bot_state="awaiting_contact")

        # "כן" is 2 chars — it would fail validate_question if this path were wrong
        r = client.post("/api/webhook/telegram", json=self._update(text="כן"))

        assert r.status_code == 200
        assert len(messages_sent) == 1                          # gentle redirect only
        assert messages_sent[0]["markup"] is not None           # keyboard still shown
        assert "לחצו על הכפתור" in messages_sent[0]["text"]    # redirect text
        assert "הכפתור הגדול" in messages_sent[0]["text"]      # UX instructions appended

    def test_awaiting_contact_phone_text_captures_lead(self, client, monkeypatch):
        """While awaiting_contact, typing a phone number captures the lead."""
        captured = {}
        monkeypatch.setattr(main, "_send_telegram_message", lambda *a, **k: None)
        self._base_rag_patches(monkeypatch, already_lead=False,
                               bot_state="awaiting_contact")
        monkeypatch.setattr(main, "_db_save_lead",
                            lambda conn, sid, cid, name, phone, summary:
                                captured.update({"phone": phone}) or "lead-id-awaiting")
        monkeypatch.setattr(main, "_alert_owner", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_mark_lead_notified", lambda c, lid: None)

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="המספר שלי הוא 0521234567"))

        assert r.status_code == 200
        assert captured.get("phone") == "0521234567"

    def test_qualification_state_cleared_when_lead_exists(self, client, monkeypatch):
        """Stale awaiting_qualification + already_lead → normal RAG, state silently cleared."""
        messages_sent = []
        state_cleared = []
        # Apply base patches first, then override _db_set_session_state with the
        # spy so the specific assertion isn't silently overwritten.
        self._base_rag_patches(monkeypatch, already_lead=True,
                               bot_state="awaiting_qualification")
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text}))
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: state_cleared.append(s))

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="שאלה רגילה"))

        assert r.status_code == 200
        assert None in state_cleared                 # state was cleared to None
        assert len(messages_sent) == 1               # normal RAG reply, no keyboard

    def test_contact_share_captures_lead_and_alerts_owner(self, client, monkeypatch):
        """Native contact share → lead saved, owner alerted, warm confirmation sent."""
        messages_sent = []
        lead_saved    = {}
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"cid": str(cid), "text": text}))
        monkeypatch.setattr(main.settings, "telegram_owner_chat_id", "OWNER_ID")
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_db_save_lead",
                            lambda conn, sid, cid, name, phone, summary:
                                lead_saved.update({"name": name, "phone": phone}) or "lead-uuid")
        monkeypatch.setattr(main, "_db_mark_lead_notified", lambda c, lid: None)

        contact_update = {"update_id": 1,
                          "message": {"chat": {"id": 555},
                                      "contact": {"phone_number": "+972501234567",
                                                  "first_name": "דנה", "last_name": "כהן"}}}
        r = client.post("/api/webhook/telegram", json=contact_update)

        assert r.status_code == 200
        # User gets a warm confirmation
        user_msgs = [m for m in messages_sent if m["cid"] == "555"]
        assert any("תודה" in m["text"] for m in user_msgs)
        # Owner gets an alert DM
        owner_msgs = [m for m in messages_sent if m["cid"] == "OWNER_ID"]
        assert len(owner_msgs) == 1
        assert "+972501234567" in owner_msgs[0]["text"]
        assert "דנה כהן" in owner_msgs[0]["text"]

    def test_contact_share_duplicate_is_silent(self, client, monkeypatch):
        """Second contact share from same user → save returns None, no double owner alert."""
        owner_alerts = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None: None)
        monkeypatch.setattr(main.settings, "telegram_owner_chat_id", "OWNER")
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_db_save_lead",
                            lambda *a, **k: None)   # ON CONFLICT → None
        monkeypatch.setattr(main, "_alert_owner",
                            lambda *a, **k: owner_alerts.append(1))

        contact_update = {"update_id": 2,
                          "message": {"chat": {"id": 777},
                                      "contact": {"phone_number": "+972509999999",
                                                  "first_name": "אלון"}}}
        r = client.post("/api/webhook/telegram", json=contact_update)

        assert r.status_code == 200
        assert owner_alerts == []   # owner NOT alerted for duplicate

    def test_regex_phone_fallback_captures_lead(self, client, monkeypatch):
        """User types their phone number → captured via regex fallback."""
        captured = {}
        monkeypatch.setattr(main, "_send_telegram_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_get_session_state", lambda c, sid: None)
        monkeypatch.setattr(main, "_db_set_session_state", lambda c, sid, s: None)
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_db_has_lead", lambda c, cid: False)
        monkeypatch.setattr(main, "_db_save_lead",
                            lambda conn, sid, cid, name, phone, summary:
                                captured.update({"phone": phone}) or "lead-uuid-regex")
        monkeypatch.setattr(main, "_alert_owner", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_mark_lead_notified", lambda c, lid: None)

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="המספר שלי הוא 0521234567"))

        assert r.status_code == 200
        assert captured.get("phone") == "0521234567"

    def test_persona_injected_into_rag_prompt(self, client, monkeypatch):
        """The persona/brand DNA is prepended to the RAG prompt."""
        captured = {}
        monkeypatch.setattr(main, "_send_telegram_message", MagicMock())
        monkeypatch.setattr(main, "_embed_text", lambda t: [0.1] * 768)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_get_session_state", lambda c, sid: None)
        monkeypatch.setattr(main, "_db_set_session_state", lambda c, sid, s: None)
        monkeypatch.setattr(main, "_db_has_lead", lambda c, cid: False)
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_retrieve_chunks", lambda c, v, top_k=5:
                            [{"content": "x", "source": "about.txt", "similarity": 0.7}])
        monkeypatch.setattr(main, "_db_save_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_touch_session", lambda c, sid: None)
        def cap(p):
            captured["p"] = p
            return "ok"
        monkeypatch.setattr(main, "_call_llm", cap)

        r = client.post("/api/webhook/telegram", json=self._update(text="שאלה על זוגיות"))

        assert r.status_code == 200
        # default persona (loaded from defaults since mock DB is empty) names Erez
        assert "ארז גרצמן" in captured["p"]


# ─── 11. App config (persona / greeting / crisis) ─────────────────────────────

class TestAppConfig:
    def test_returns_default_when_db_empty(self, client):
        """Empty app_config table → hardcoded default (here, the crisis message)."""
        val = main._get_config("crisis.message")
        assert "1201" in val

    def test_returns_db_value_when_present(self, client):
        mock_conn, mock_cursor = _patch_conn(client)
        mock_cursor.fetchall.return_value = [("persona.system", "CUSTOM VOICE")]
        main._config_cache, main._config_cache_ts = {}, 0.0   # force a reload

        assert main._get_config("persona.system") == "CUSTOM VOICE"

    def test_unknown_key_returns_empty_string(self, client):
        main._config_cache, main._config_cache_ts = {}, 0.0
        assert main._get_config("nope.not.here") == ""

    def test_is_crisis_detects_hebrew_and_english(self):
        assert main.is_crisis("אני רוצה למות")
        assert main.is_crisis("I want to kill myself")
        assert not main.is_crisis("מה השירותים שלכם?")
        assert not main.is_crisis("how much does a session cost?")


# ─── 12. Sprint 1A — state machine resilience ─────────────────────────────────

class TestEscapeIntent:
    """Pure-function tests for the opt-out detector."""
    def test_detects_hebrew_lo(self):        assert main._is_escape_intent("לא")
    def test_detects_batel(self):            assert main._is_escape_intent("בטל בבקשה")
    def test_detects_stop_english(self):     assert main._is_escape_intent("stop")
    def test_detects_never_mind(self):       assert main._is_escape_intent("never mind")
    def test_benign_not_detected(self):      assert not main._is_escape_intent("מה השירותים?")
    def test_lo_inside_word_not_matched(self):
        # "לאחרונה" contains "לא" but as a substring with \b it should NOT match
        assert not main._is_escape_intent("לאחרונה")


class TestContactStateHelpers:
    """Pure-function tests for awaiting_contact encoding helpers."""
    def test_make_contact_state_default(self): assert main._make_contact_state() == "awaiting_contact:0"
    def test_make_contact_state_n(self):       assert main._make_contact_state(2) == "awaiting_contact:2"
    def test_is_awaiting_contact_true(self):   assert main._is_awaiting_contact("awaiting_contact:0")
    def test_is_awaiting_contact_false(self):  assert not main._is_awaiting_contact("awaiting_qualification")
    def test_is_awaiting_contact_none(self):   assert not main._is_awaiting_contact(None)
    def test_parse_retry_zero(self):           assert main._parse_contact_retry("awaiting_contact:0") == 0
    def test_parse_retry_two(self):            assert main._parse_contact_retry("awaiting_contact:2") == 2
    def test_parse_retry_bad_input(self):      assert main._parse_contact_retry(None) == 0


class TestFormatLeadThanks:
    """Cosmetic fix: no double-space when name is absent."""
    def test_with_name(self):
        result = main._format_lead_thanks("דנה")
        assert "תודה דנה 🙏" in result
        assert "  " not in result          # no double space
    def test_without_name(self):
        result = main._format_lead_thanks(None)
        assert result.startswith("תודה 🙏")
        assert "  " not in result          # no double space
    def test_empty_string_name(self):
        result = main._format_lead_thanks("")
        assert result.startswith("תודה 🙏")
        assert "  " not in result
    def test_whitespace_only_name(self):
        result = main._format_lead_thanks("   ")
        assert result.startswith("תודה 🙏")


class TestBotStateTTL:
    """Unit tests for _db_get_session_state TTL expiry logic."""
    def test_returns_state_when_not_expired(self):
        import datetime
        mock_conn, mock_cursor = _make_mock_conn()
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        mock_cursor.fetchone.return_value = ("awaiting_contact:0", future)
        assert main._db_get_session_state(mock_conn, "s1") == "awaiting_contact:0"

    def test_returns_none_when_expired(self):
        import datetime
        mock_conn, mock_cursor = _make_mock_conn()
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        mock_cursor.fetchone.return_value = ("awaiting_contact:0", past)
        assert main._db_get_session_state(mock_conn, "s1") is None

    def test_returns_none_when_no_expiry_column(self):
        """Legacy rows without an expires_at value are treated as non-expiring."""
        mock_conn, mock_cursor = _make_mock_conn()
        mock_cursor.fetchone.return_value = ("awaiting_qualification", None)
        assert main._db_get_session_state(mock_conn, "s1") == "awaiting_qualification"

    def test_returns_none_for_missing_session(self):
        mock_conn, mock_cursor = _make_mock_conn()
        mock_cursor.fetchone.return_value = None
        assert main._db_get_session_state(mock_conn, "s1") is None


class TestWebhookResilienceEdgeCases:
    """Webhook-level tests for Sprint 1A escape, retry, and crisis-clear."""

    def _update(self, text="שלום", chat_id=555):
        return {"update_id": 1,
                "message": {"chat": {"id": chat_id, "type": "private"}, "text": text}}

    def _base(self, monkeypatch, *, bot_state=None, already_lead=False):
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_get_session_state", lambda c, sid: bot_state)
        monkeypatch.setattr(main, "_db_set_session_state", lambda c, sid, s: None)
        monkeypatch.setattr(main, "_db_has_lead", lambda c, cid: already_lead)
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_db_touch_session", lambda c, sid: None)
        monkeypatch.setattr(main, "_db_save_message", lambda *a, **k: None)

    def test_escape_clears_state_from_awaiting_qualification(self, client, monkeypatch):
        """'לא' while awaiting_qualification → graceful exit, state cleared."""
        state_cleared = []
        sent = []
        self._base(monkeypatch, bot_state="awaiting_qualification")
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: state_cleared.append(s))
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, **k: sent.append(text))

        r = client.post("/api/webhook/telegram", json=self._update(text="לא"))

        assert r.status_code == 200
        assert None in state_cleared                    # state cleared
        assert any("בסדר גמור" in m for m in sent)     # graceful exit message

    def test_escape_clears_state_from_awaiting_contact(self, client, monkeypatch):
        """'בטל' while awaiting_contact → graceful exit, NOT the retry keyboard."""
        state_cleared = []
        sent = []
        self._base(monkeypatch, bot_state="awaiting_contact:1")
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: state_cleared.append(s))
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, **k: sent.append(text))

        r = client.post("/api/webhook/telegram", json=self._update(text="בטל"))

        assert r.status_code == 200
        assert None in state_cleared
        assert all("לחצו על הכפתור" not in m for m in sent)   # no retry keyboard

    def test_awaiting_contact_retry_counter_increments(self, client, monkeypatch):
        """Non-phone, non-escape in awaiting_contact:0 → state becomes awaiting_contact:1."""
        states_set = []
        self._base(monkeypatch, bot_state="awaiting_contact:0")
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: states_set.append(s))
        monkeypatch.setattr(main, "_send_telegram_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_send_contact_keyboard", lambda *a, **k: None)

        r = client.post("/api/webhook/telegram", json=self._update(text="כן"))

        assert r.status_code == 200
        assert "awaiting_contact:1" in states_set

    def test_retry_exhaustion_clears_state_and_sends_graceful_exit(self, client, monkeypatch):
        """After MAX_CONTACT_RETRIES non-phone replies → graceful exit + state cleared."""
        state_cleared = []
        sent = []
        self._base(monkeypatch,
                   bot_state=f"awaiting_contact:{main._MAX_CONTACT_RETRIES}")
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: state_cleared.append(s))
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, **k: sent.append(text))

        r = client.post("/api/webhook/telegram", json=self._update(text="כן שוב"))

        assert r.status_code == 200
        assert None in state_cleared                              # state cleared
        assert any("ללא לחץ" in m for m in sent)                 # graceful message

    def test_crisis_clears_funnel_state(self, client, monkeypatch):
        """Crisis response is sent first; bot_state is then cleared (best-effort)."""
        state_cleared = []
        monkeypatch.setattr(main, "_send_telegram_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_get_session_state",
                            lambda c, sid: "awaiting_contact:0")
        monkeypatch.setattr(main, "_db_set_session_state",
                            lambda c, sid, s: state_cleared.append(s))

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני לא רוצה לחיות"))

        assert r.status_code == 200
        assert None in state_cleared   # state cleared after crisis response


# ─── 13. Sprint 1B — CRM lead sync (HubSpot provider) ─────────────────────────

class TestCrmFormatPhone:
    def test_israeli_local(self):     assert main._crm_format_phone("0521234567") == "+972521234567"
    def test_already_e164(self):      assert main._crm_format_phone("+972521234567") == "+972521234567"
    def test_972_no_plus(self):       assert main._crm_format_phone("972521234567") == "+972521234567"
    def test_strips_separators(self): assert main._crm_format_phone("052-123 4567") == "+972521234567"
    def test_empty(self):             assert main._crm_format_phone("") == ""


class TestCrmProviderDispatch:
    """The swappable adapter: provider selection + the credential-free fake."""
    def test_disabled_when_no_provider(self, monkeypatch):
        monkeypatch.setattr(main.settings, "crm_provider", "")
        assert main._crm_enabled() is False
        assert main._crm_sync_lead("x", "0521234567", "y") is None

    def test_hubspot_enabled_requires_token(self, monkeypatch):
        monkeypatch.setattr(main.settings, "crm_provider", "hubspot")
        monkeypatch.setattr(main.settings, "hubspot_private_token", "")
        assert main._crm_enabled() is False
        monkeypatch.setattr(main.settings, "hubspot_private_token", "pat-x")
        assert main._crm_enabled() is True

    def test_fake_provider_is_deterministic_and_offline(self, monkeypatch):
        monkeypatch.setattr(main.settings, "crm_provider", "fake")
        monkeypatch.setattr(main, "_hubspot_request",
                            lambda *a, **k: pytest.fail("network used in fake mode"))
        a = main._crm_sync_lead("דנה", "0521234567", "y")
        b = main._crm_sync_lead("דנה", "0521234567", "y")
        assert a and a == b and a.startswith("fake-")


class TestHubspotUpsertContact:
    """Idempotency layer 2: search-by-phone then create-or-update."""
    def _enable(self, monkeypatch):
        monkeypatch.setattr(main.settings, "crm_provider", "hubspot")
        monkeypatch.setattr(main.settings, "hubspot_private_token", "pat-x")
        monkeypatch.setattr(main.settings, "hubspot_intent_property", "")   # note path

    def test_creates_when_not_found(self, monkeypatch):
        self._enable(monkeypatch)
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith("/search"):
                return {"results": []}                  # not found
            if path == "/crm/v3/objects/contacts":
                return {"id": "c1"}
            return {}
        monkeypatch.setattr(main, "_hubspot_request", fake)

        cid = main._hubspot_upsert_contact("דנה", "0521234567", "על זוגיות")
        assert cid == "c1"
        mp = [(m, p) for m, p, _ in calls]
        assert ("POST", "/crm/v3/objects/contacts") in mp       # created
        assert ("POST", "/crm/v3/objects/notes") in mp          # intent → note
        create = next(pl for m, p, pl in calls if p == "/crm/v3/objects/contacts")
        assert create["properties"]["phone"] == "+972521234567"
        assert create["properties"]["lifecyclestage"] == "lead"

    def test_idempotent_update_when_found(self, monkeypatch):
        self._enable(monkeypatch)
        calls = []
        def fake(method, path, payload=None):
            calls.append((method, path))
            if path.endswith("/search"):
                return {"results": [{"id": "existing99"}]}
            return {}
        monkeypatch.setattr(main, "_hubspot_request", fake)

        cid = main._hubspot_upsert_contact("דנה", "0521234567", None)
        assert cid == "existing99"
        assert ("PATCH", "/crm/v3/objects/contacts/existing99") in calls   # updated
        assert ("POST", "/crm/v3/objects/contacts") not in calls           # never re-created

    def test_custom_property_skips_note(self, monkeypatch):
        self._enable(monkeypatch)
        monkeypatch.setattr(main.settings, "hubspot_intent_property", "nexus_intent")
        paths = []
        def fake(method, path, payload=None):
            paths.append(path)
            if path.endswith("/search"):
                return {"results": []}
            if path == "/crm/v3/objects/contacts":
                assert payload["properties"]["nexus_intent"] == "בגידה"
                return {"id": "c2"}
            return {}
        monkeypatch.setattr(main, "_hubspot_request", fake)
        assert main._hubspot_upsert_contact(None, "0521234567", "בגידה") == "c2"
        assert "/crm/v3/objects/notes" not in paths


class TestHubspotPipelineDiscovery:
    def test_auto_discovers_default_first_stage(self, monkeypatch):
        main._hubspot_pipeline_cache = None
        monkeypatch.setattr(main.settings, "hubspot_pipeline_id", "")
        monkeypatch.setattr(main.settings, "hubspot_stage_id", "")
        monkeypatch.setattr(main, "_hubspot_request", lambda m, p, pl=None: {
            "results": [{
                "id": "default", "displayOrder": 0,
                "stages": [{"id": "s_appt", "displayOrder": 0},
                           {"id": "s_qual", "displayOrder": 1}],
            }]
        })
        assert main._hubspot_resolve_stage() == ("default", "s_appt")
        main._hubspot_pipeline_cache = None   # don't leak cache to other tests

    def test_configured_ids_take_precedence(self, monkeypatch):
        main._hubspot_pipeline_cache = None
        monkeypatch.setattr(main.settings, "hubspot_pipeline_id", "P")
        monkeypatch.setattr(main.settings, "hubspot_stage_id", "S")
        monkeypatch.setattr(main, "_hubspot_request",
                            lambda *a, **k: pytest.fail("should not hit the API"))
        assert main._hubspot_resolve_stage() == ("P", "S")


class TestHubspotSyncLead:
    def test_creates_contact_and_deal(self, monkeypatch):
        monkeypatch.setattr(main.settings, "crm_provider", "hubspot")
        monkeypatch.setattr(main.settings, "hubspot_private_token", "pat-x")
        monkeypatch.setattr(main, "_hubspot_upsert_contact", lambda n, p, i: "c123")
        deals = []
        monkeypatch.setattr(main, "_hubspot_create_deal",
                            lambda cid, name: deals.append((cid, name)))
        assert main._crm_sync_lead("דנה", "0521234567", "y") == "c123"
        assert deals == [("c123", "דנה")]               # deal created + associated

    def test_no_deal_when_contact_fails(self, monkeypatch):
        monkeypatch.setattr(main.settings, "crm_provider", "hubspot")
        monkeypatch.setattr(main.settings, "hubspot_private_token", "pat-x")
        monkeypatch.setattr(main, "_hubspot_upsert_contact", lambda n, p, i: None)
        called = []
        monkeypatch.setattr(main, "_hubspot_create_deal", lambda *a: called.append(1))
        assert main._crm_sync_lead("x", "0521234567", "y") is None
        assert called == []


class TestFinalizeLead:
    """The single post-save funnel: best-effort, never raises, stamps state."""
    def test_marks_synced_on_success(self, client, monkeypatch):
        monkeypatch.setattr(main, "_alert_owner", lambda *a, **k: None)
        monkeypatch.setattr(main, "_crm_sync_lead", lambda n, p, i: "c999")
        notified, synced = [], []
        monkeypatch.setattr(main, "_db_mark_lead_notified",
                            lambda c, lid: notified.append(lid))
        monkeypatch.setattr(main, "_db_mark_lead_synced",
                            lambda c, lid, eid: synced.append((lid, eid)))
        main._finalize_lead("lead1", "דנה", "0521234567", "y", "777")
        assert notified == ["lead1"]
        assert synced == [("lead1", "c999")]

    def test_crm_miss_still_notifies_and_leaves_unsynced(self, client, monkeypatch):
        monkeypatch.setattr(main, "_alert_owner", lambda *a, **k: None)
        monkeypatch.setattr(main, "_crm_sync_lead", lambda *a, **k: None)
        notified, synced = [], []
        monkeypatch.setattr(main, "_db_mark_lead_notified",
                            lambda c, lid: notified.append(lid))
        monkeypatch.setattr(main, "_db_mark_lead_synced",
                            lambda c, lid, eid: synced.append(lid))
        main._finalize_lead("lead2", None, "0521234567", "y", "777")
        assert notified == ["lead2"]
        assert synced == []          # unsynced → reconciler retries later

    def test_owner_alert_exception_does_not_block_sync(self, client, monkeypatch):
        def boom(*a, **k): raise RuntimeError("telegram down")
        monkeypatch.setattr(main, "_alert_owner", boom)
        monkeypatch.setattr(main, "_crm_sync_lead", lambda *a, **k: "c1")
        synced = []
        monkeypatch.setattr(main, "_db_mark_lead_notified", lambda c, l: None)
        monkeypatch.setattr(main, "_db_mark_lead_synced",
                            lambda c, l, eid: synced.append(eid))
        main._finalize_lead("lead3", None, "0521234567", "y", "777")   # must not raise
        assert synced == ["c1"]


class TestCronCrmSync:
    def test_rejects_bad_secret(self, client, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "s3cr3t")
        r = client.get("/api/cron/crm-sync", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_skipped_when_crm_disabled(self, client, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "")     # guard off (dev)
        monkeypatch.setattr(main, "_crm_enabled", lambda: False)
        r = client.get("/api/cron/crm-sync")
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"

    def test_processes_pending_leads(self, client, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "")
        monkeypatch.setattr(main, "_crm_enabled", lambda: True)
        _patch_conn(client, fetchall=[("lead1", "דנה", "0521234567", "y")])
        synced = []
        monkeypatch.setattr(main, "_crm_sync_lead", lambda n, p, i: "cX")
        monkeypatch.setattr(main, "_db_mark_lead_synced",
                            lambda c, lid, eid: synced.append((lid, eid)))
        r = client.get("/api/cron/crm-sync")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["synced"] == 1
        assert synced == [("lead1", "cX")]
