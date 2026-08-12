"""
Unit tests for the SQL text objects in queries.py.

These check the compiled SQL text, not live results — a DB-backed check of
the actual before/after row counts was run manually against the pipeline's
Supabase instance (28 -> 23 ambiguous rows, 5 stale rows removed) rather than
committed as a test, since job-search-dashboard has no DB credentials of its
own and this repo should not depend on the sibling pipeline repo's .env.
"""
import re

from queries import REVIEW_QUEUE_SQL, STATEMENTS


def _sql(stmt):
    return str(stmt).lower()


def test_review_queue_excludes_stale_postings():
    sql = _sql(REVIEW_QUEUE_SQL)
    assert re.search(r"r\.is_stale\s*=\s*false", sql), (
        "review_queue must filter out raw_postings.is_stale rows so stale "
        "postings never reach the Review Queue tab"
    )


def test_review_queue_still_scoped_to_ambiguous_forwarded():
    # The stale filter is additive — it must not accidentally widen the
    # existing first_pass_result scope.
    sql = _sql(REVIEW_QUEUE_SQL)
    assert "first_pass_result = 'ambiguous_forwarded'" in sql


def test_review_queue_is_registered_under_its_name():
    assert STATEMENTS["review_queue"] is REVIEW_QUEUE_SQL


def test_review_queue_selects_qualified_opportunity_id():
    # The Approve/Reject select-then-act UI keys off this — without it
    # there is nothing to pass to mutations.record_decision.
    sql = _sql(REVIEW_QUEUE_SQL)
    assert "q.id" in sql and "qualified_opportunity_id" in sql


def test_review_queue_excludes_already_actioned_rows():
    sql = _sql(REVIEW_QUEUE_SQL)
    assert re.search(r"not exists\s*\(\s*select 1 from applications", sql), (
        "review_queue must exclude opportunities that already have an "
        "applications row, or an actioned row would reappear as pending"
    )
