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
    mock_cursor.fetchone.return_value  = fetchone_return or (1,)
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

    def test_booking_intent_sends_contact_keyboard(self, client, monkeypatch):
        """When user expresses booking intent and has no lead, keyboard is sent after reply."""
        messages_sent = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text, "markup": reply_markup}))
        monkeypatch.setattr(main, "_embed_text", lambda t: [0.1] * 768)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_retrieve_chunks", lambda c, v, top_k=5:
                            [{"content": "x", "source": "services.txt", "similarity": 0.7}])
        monkeypatch.setattr(main, "_db_has_lead", lambda c, cid: False)   # no lead yet
        monkeypatch.setattr(main, "_call_llm", lambda p: "הנה מידע על ייעוץ")
        monkeypatch.setattr(main, "_db_save_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_touch_session", lambda c, sid: None)

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני מעוניין בפגישת ייעוץ"))

        assert r.status_code == 200
        assert len(messages_sent) == 2              # RAG reply + keyboard prompt
        assert messages_sent[1]["markup"] is not None
        assert messages_sent[1]["markup"].get("keyboard") is not None

    def test_no_keyboard_when_lead_already_exists(self, client, monkeypatch):
        """Booking intent + existing lead → reply only, no second keyboard prompt."""
        messages_sent = []
        monkeypatch.setattr(main, "_send_telegram_message",
                            lambda cid, text, reply_markup=None:
                                messages_sent.append({"text": text}))
        monkeypatch.setattr(main, "_embed_text", lambda t: [0.1] * 768)
        monkeypatch.setattr(main, "_db_get_or_create_telegram_session", lambda c, cid: "s1")
        monkeypatch.setattr(main, "_db_load_history", lambda c, sid, limit=12: [])
        monkeypatch.setattr(main, "_retrieve_chunks", lambda c, v, top_k=5:
                            [{"content": "x", "source": "services.txt", "similarity": 0.7}])
        monkeypatch.setattr(main, "_db_has_lead", lambda c, cid: True)   # already captured
        monkeypatch.setattr(main, "_call_llm", lambda p: "הנה מידע")
        monkeypatch.setattr(main, "_db_save_message", lambda *a, **k: None)
        monkeypatch.setattr(main, "_db_touch_session", lambda c, sid: None)

        r = client.post("/api/webhook/telegram",
                        json=self._update(text="אני מעוניין בפגישת ייעוץ"))

        assert r.status_code == 200
        assert len(messages_sent) == 1              # RAG reply only

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
