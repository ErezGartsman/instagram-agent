"""
tests.test_cockpit_agent_runs_uuid_cast — regression for the `uuid = text`
class of bug on GET /api/cockpit/agents/runs/{person_id}.

agent_actions.agent_run_id is uuid, but the endpoint gathers run ids as
str()-ified values and feeds them to `= ANY(%s)`. psycopg2 adapts a Python str
list to a text[] literal, so without an explicit `::uuid[]` cast Postgres
raises `operator does not exist: uuid = text` (the same defect found in the
Flows simulation path). DB mocked, auth overridden — Pattern C house style.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app


@pytest.fixture
def client():
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


def test_actions_query_casts_run_ids_to_uuid_array(client):
    run_row = ("55555555-5555-5555-5555-555555555555", "qualifier", "success",
               "webhook", {}, None, None, None)
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    # 1st fetchall = agent_runs; 2nd = agent_actions (empty is fine, the query
    # still executes because run_ids is non-empty).
    cur.fetchall.side_effect = [[run_row], []]
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value = cur

    with patch.object(main, "get_db_conn", MagicMock(return_value=conn)):
        r = client.get("/api/cockpit/agents/runs/55555555-5555-5555-5555-555555555555")
    assert r.status_code == 200
    actions_sql = [c.args[0] for c in cur.execute.call_args_list if "agent_actions" in c.args[0]]
    assert actions_sql and "ANY(%s::uuid[])" in actions_sql[0]
