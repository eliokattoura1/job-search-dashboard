"""
Unit tests for mutations.py, using a mocked SQLAlchemy engine throughout.

These deliberately never touch a real database: applications is live
production pipeline data, and a test that inserted into it would corrupt
that data rather than verify anything. record_decision's SQL is exercised
against a fake connection instead; the INSERT itself was checked by hand
by inspecting the compiled statement and rehearsing the ON CONFLICT path
against schema.sql's UNIQUE constraint (schema.sql:418), not by writing
rows into Supabase.
"""
from unittest.mock import MagicMock

import mutations


def _engine_returning(row_or_none):
    """Build a mock engine whose `engine.begin()` context yields a connection
    whose execute(...).first() returns `row_or_none`."""
    conn = MagicMock()
    conn.execute.return_value.first.return_value = row_or_none
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    return engine, conn


def test_record_decision_returns_true_when_inserted():
    engine, conn = _engine_returning((7,))  # RETURNING id found a row
    recorded = mutations.record_decision(engine, 42, mutations.STATUS_APPROVED, "elio")
    assert recorded is True
    params = conn.execute.call_args.args[1]
    assert params == {
        "qualified_opportunity_id": 42,
        "status": mutations.STATUS_APPROVED,
        "approved_by": "elio",
    }


def test_record_decision_returns_false_on_conflict():
    engine, _conn = _engine_returning(None)  # ON CONFLICT DO NOTHING, no row
    recorded = mutations.record_decision(engine, 42, mutations.STATUS_REJECTED, "elio")
    assert recorded is False


def test_status_values_match_application_status_enum():
    # application_status_enum (agent-build/sql/schema.sql) only defines
    # 'rejected_by_human', not 'rejected' — using the wrong literal here
    # would fail at insert time with an invalid-enum-literal error.
    assert mutations.STATUS_APPROVED == "approved"
    assert mutations.STATUS_REJECTED == "rejected_by_human"


def test_record_decision_sql_is_idempotent_on_conflict():
    sql = str(mutations.RECORD_DECISION_SQL).lower()
    assert "on conflict (qualified_opportunity_id) do nothing" in sql
    assert "returning id" in sql


class _FakeUser:
    def __init__(self, email=None):
        if email is not None:
            self.email = email


class _FakeSt:
    def __init__(self, user):
        self.user = user


def test_get_actor_uses_authenticated_email_when_present():
    st = _FakeSt(_FakeUser(email="reviewer@example.com"))
    assert mutations.get_actor(st) == "reviewer@example.com"


def test_get_actor_falls_back_to_placeholder_when_no_email():
    st = _FakeSt(_FakeUser(email=None))
    assert mutations.get_actor(st) == "elio"


def test_get_actor_falls_back_to_placeholder_when_no_auth_configured():
    class _NoUserSt:
        pass  # no .user attribute at all — unauthenticated, no OIDC configured

    assert mutations.get_actor(_NoUserSt()) == "elio"
