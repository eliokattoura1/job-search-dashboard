"""
Write path for human approve/reject decisions on the Review Queue.

Deliberately split from queries.py, which documents itself as SELECT-only —
this module is where INSERTs live instead of blurring that boundary.

Per brief §11, human approval is a permanent step, not a phase-one stopgap:
recording a decision here only sets status + who + when. cv_variant_used and
cv_file_url stay NULL until the tailoring engine (§10, not yet built) exists
and writes them; nothing in this module ever touches those two columns.
"""
from sqlalchemy import text

# application_status_enum (agent-build/sql/schema.sql) defines
# 'rejected_by_human', not 'rejected' — using 'rejected' would fail with an
# invalid-enum-literal error rather than just recording the wrong value.
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected_by_human"

# applications has no rejection-reason column (schema.sql:416-428), so reject
# records the same fields as approve, just with a different status — no
# reason is captured because there is nowhere to put one.

# ON CONFLICT DO NOTHING + RETURNING id makes this idempotent against the
# UNIQUE constraint on qualified_opportunity_id (schema.sql:418): a second
# click, or two reviewers actioning the same row, finds no id in the result
# instead of raising IntegrityError, so the caller can tell "recorded" from
# "already decided" without parsing a DB exception.
RECORD_DECISION_SQL = text("""
    INSERT INTO applications (qualified_opportunity_id, status, approved_by, approved_at)
    VALUES (:qualified_opportunity_id, :status, :approved_by, now())
    ON CONFLICT (qualified_opportunity_id) DO NOTHING
    RETURNING id
""")


def record_decision(engine, qualified_opportunity_id, status, actor):
    """
    Insert one approve/reject decision.

    Returns True if this call recorded it, False if a row for this
    qualified_opportunity_id already existed (someone else's click won the
    race) — never raises on that race.
    """
    with engine.begin() as conn:
        result = conn.execute(RECORD_DECISION_SQL, {
            "qualified_opportunity_id": qualified_opportunity_id,
            "status": status,
            "approved_by": actor,
        })
        return result.first() is not None


def get_actor(st):
    """
    Best-effort reviewer identity for approved_by.

    st.user is only populated when the deployment has OIDC viewer auth
    configured; this app has none, so it falls back to a static placeholder
    rather than leaving approved_by NULL, which would make a decision
    impossible to attribute. Takes the streamlit module as a parameter so
    this stays importable/testable without a running Streamlit session.
    """
    try:
        email = getattr(st.user, "email", None)
    except Exception:
        email = None
    return email or "elio"
