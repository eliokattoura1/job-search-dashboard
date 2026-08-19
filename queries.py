"""
Read-only SQL for the daily-check dashboard. Every statement here is a SELECT;
nothing in this package writes to the database.

The forward-queue query mirrors the pipeline's own Excel export rather than
re-deriving it, so the two cannot drift into disagreeing about what "the queue"
is. It adds `source` (which this screen filters on) and omits the export's
audit-only derivation of which ingest run first saw each posting.

The filter is on `first_pass_result`, NOT `classification` — the latter is a
Postgres enum holding only 'strong_match' | 'potential_match' | 'not_qualified',
so filtering it on 'pass'/'ambiguous_forwarded' is rejected outright as an
invalid enum literal rather than merely returning nothing.
"""
from sqlalchemy import text

# Stage order is the pipeline's execution order, not alphabetical — a reader
# scanning the table is checking "how far did tonight get", which only reads
# correctly in run order. Applied in app.py after the fetch, since DISTINCT ON
# forces its own ORDER BY here.
#
# Must list EVERY stage the pipeline executes. A stage missing from this list
# still renders (app.py sorts unknown stages to the end via the len() fallback),
# but it silently loses its "never run" tile — which is precisely the signal that
# matters for a stage that has never once been recorded.
STAGE_ORDER = ["ingest", "dedupe", "staleness", "prefilter", "detail_check"]

# DISTINCT ON (stage) + ORDER BY stage, started_at DESC = the newest row per
# stage. Deliberately NOT filtered to one run_id: when a run dies partway (a
# CI job killed at its timeout mid-ingest, say), the newest ingest row and the
# newest prefilter row legitimately belong to DIFFERENT runs, and showing each
# stage's own last outcome is what makes that visible. run_id is selected so
# mismatched stages are obvious rather than implied.
LATEST_RUNS_SQL = text("""
    SELECT DISTINCT ON (stage)
           stage, run_id, status, started_at, finished_at, error_detail,
           rows_fetched, rows_inserted, rows_updated,
           rows_processed, rows_duplicate, rows_embedded,
           rows_stale, rows_returned,
           rows_pass, rows_excluded, rows_ambiguous
    FROM pipeline_runs
    ORDER BY stage, started_at DESC
""")

VERDICT_COUNTS_SQL = text("""
    SELECT first_pass_result, count(*) AS n
    FROM qualified_opportunities
    GROUP BY first_pass_result
""")

# unnest() because reject_reasons is TEXT[] — a row carrying two reasons counts
# once against each, so these sum to more than the excluded row count. That is
# the intended reading (how often does each gate fire), not double counting.
REJECT_REASONS_SQL = text("""
    SELECT reason, count(*) AS n
    FROM qualified_opportunities, unnest(reject_reasons) AS reason
    WHERE first_pass_result = 'excluded'
    GROUP BY reason
    ORDER BY n DESC
""")

FORWARD_QUEUE_SQL = text("""
    SELECT q.first_pass_result,
           COALESCE(c.name, r.company_name) AS company,
           r.title,
           s.name        AS source,
           r.location,
           r.url,
           r.salary_raw,
           q.salary_estimate_usd_month,
           r.is_stale,
           r.stale_since,
           -- Whole days the source has not returned this posting. NULL for live
           -- rows, which renders blank rather than a misleading 0.
           EXTRACT(DAY FROM now() - r.stale_since)::int AS stale_days,
           r.fetched_at,
           r.first_seen_at,
           r.id          AS posting_id
    FROM qualified_opportunities q
    JOIN raw_postings r ON r.id = q.raw_posting_id
    JOIN sources s      ON s.id = r.source_id
    LEFT JOIN companies c ON c.id = r.company_id
    WHERE q.first_pass_result = ANY(:results)
    -- Live rows first, then most-recently-fetched. Stale rows are down-ranked,
    -- never withheld: a posting the source stopped returning is likely closed
    -- but not provably so, and hiding it would make the omission invisible to
    -- the reviewer. Same ordering rationale as the export.
    ORDER BY r.is_stale ASC, r.fetched_at DESC
""")

# generate_series drives the day axis so a day with ZERO new rows appears as an
# explicit 0 instead of vanishing from the result. That gap is the whole point
# of this chart — a broken ingest shows up as a visible trough, whereas a
# missing row would just narrow the x-axis and look normal.
#
# Both counts are "rows first created on that day": first_seen_at is written
# once at insert and never updated by the pipeline's upserts, and
# qualified_opportunities.created_at likewise survives re-evaluation. So neither
# line moves when a row is merely re-fetched or re-scored. Dates resolve in the
# server's timezone (UTC here).
DAILY_TREND_SQL = text("""
    WITH days AS (
        SELECT generate_series(
            CURRENT_DATE - (:days - 1) * INTERVAL '1 day',
            CURRENT_DATE,
            INTERVAL '1 day'
        )::date AS day
    )
    SELECT d.day,
           (SELECT count(*) FROM raw_postings r
             WHERE r.first_seen_at::date = d.day) AS new_postings,
           (SELECT count(*) FROM qualified_opportunities q
             WHERE q.created_at::date = d.day)    AS new_opportunities
    FROM days d
    ORDER BY d.day
""")

# Headline totals that aren't per-day: cheap enough to run every refresh.
CORPUS_TOTALS_SQL = text("""
    SELECT (SELECT count(*) FROM raw_postings)                          AS raw_total,
           (SELECT count(*) FROM raw_postings WHERE is_duplicate)       AS raw_duplicates,
           (SELECT count(*) FROM raw_postings WHERE is_stale)           AS raw_stale,
           (SELECT count(*) FROM raw_postings WHERE embedding IS NULL
                                                AND NOT is_duplicate)   AS missing_embeddings,
           (SELECT count(*) FROM qualified_opportunities)               AS qo_total
""")


# ---------------------------------------------------------------------------
# Stakeholder-facing statements (candidate-facing tabs, added 2026-08-11).
#
# These share the same DB/read-only posture as everything above but answer a
# different question than the technical tabs do — "what has the search found
# so far", not "did last night's run work". Two conventions specific to this
# section:
#
#   * "Opportunities" means qualified_opportunities rows with
#     first_pass_result IN ('pass', 'ambiguous_forwarded') — i.e. everything
#     NOT excluded, the same definition FORWARD_QUEUE_SQL above already uses
#     for its two queues. 'excluded' rows are not opportunities.
#   * Source and reject-reason values come straight out of the database
#     (connector/table names, internal reason codes) and are relabeled for
#     display via SOURCE_DISPLAY_NAMES / REASON_LABELS below, in app.py, right
#     before rendering — never in SQL, so the underlying value stays the join
#     key and the label stays purely cosmetic.
# ---------------------------------------------------------------------------

# raw_postings.source_id -> sources.name -> a name a candidate would recognize.
# Deliberately a lookup with an explicit fallback in app.py (title-cased raw
# name) rather than a database column: these are cosmetic and change if a
# clearer label is wanted later, which should never require a migration.
SOURCE_DISPLAY_NAMES = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workable": "Workable",
    "remoteok": "RemoteOK",
    "remotive": "Remotive",
    "himalayas": "Himalayas",
    "weworkremotely": "We Work Remotely",
    "workingnomads": "Working Nomads",
    "eures": "EURES",
    "landingjobs": "Landing.jobs",
    "mycareersfuture": "MyCareersFuture",
    "arbeitnow": "Arbeitnow",
    "jobtechdev": "JobTech Dev",
}

# prefilter's fixed reject_reasons vocabulary (pipeline/prefilter.py
# VALID_REASON_CODES), relabeled into plain language for display. Every code
# the pipeline can currently produce is listed so a new/unrecognized code
# fails visibly (falls back to the raw code in app.py) rather than silently
# rendering blank.
REASON_LABELS = {
    "citizenship_or_residency_required": "Requires citizenship/residency the candidate doesn't hold",
    "local_work_permit_required": "Requires a local work permit",
    "work_authorization_mismatch": "Location not covered by current work authorization",
    "onsite_or_hybrid_required": "Requires on-site attendance",
    "timezone_incompatible": "Timezone doesn't overlap enough",
    "salary_below_minimum": "Salary below minimum",
    "role_not_in_taxonomy": "Not a targeted role type",
    "missing_technical_skills": "Missing required technical skills",
    "seniority_mismatch": "Seniority level doesn't match",
    "portfolio_mismatch": "Portfolio doesn't match what's required",
    "deadline_passed": "Application deadline has passed",
    "low_company_credibility": "Company didn't meet credibility criteria",
    "engagement_type_mismatch": "Employment type doesn't match (e.g. contract vs. full-time)",
}

# One row: the four funnel stages. Ingested/Prefiltered come from the latest
# recorded run of each stage (mirrors LATEST_RUNS_SQL's own "newest row per
# stage" logic, just narrowed to the one number each stage is known for).
# Qualified/Applications Submitted read directly off their tables rather than
# off a pipeline_runs stage, because no stage populates them yet — see the
# Funnel tab in app.py, which shows "Coming soon" instead of a bare 0 when a
# stage genuinely has no data behind it yet, rather than implying that stage
# ran and found nothing.
FUNNEL_SQL = text("""
    SELECT
        (SELECT rows_fetched FROM pipeline_runs
          WHERE stage = 'ingest' ORDER BY started_at DESC LIMIT 1)    AS ingested,
        (SELECT rows_processed FROM pipeline_runs
          WHERE stage = 'prefilter' ORDER BY started_at DESC LIMIT 1) AS prefiltered,
        (SELECT count(*) FROM qualified_opportunities
          WHERE deep_review_score IS NOT NULL)                       AS qualified,
        (SELECT count(*) FROM applications
          WHERE submitted_at IS NOT NULL)                             AS applications_submitted
""")

OPPORTUNITIES_BY_SOURCE_SQL = text("""
    SELECT s.name AS source, count(*) AS n
    FROM qualified_opportunities q
    JOIN raw_postings r ON r.id = q.raw_posting_id
    JOIN sources s      ON s.id = r.source_id
    WHERE q.first_pass_result IN ('pass', 'ambiguous_forwarded')
    GROUP BY s.name
    ORDER BY n DESC
""")

# Distinct location strings for opportunities only, grouped in SQL and bucketed
# into a region in Python — same division of labor as the technical tab's
# LOCATION_COUNTS_SQL above (region vocabulary lives in regions.py, not here
# or in a DB column). Unlike that query this is scoped to opportunities, not
# every raw posting, since the region breakdown here is answering "where are
# the opportunities", not "where does the whole corpus sit".
OPPORTUNITIES_BY_LOCATION_SQL = text("""
    SELECT r.location, count(*) AS n
    FROM qualified_opportunities q
    JOIN raw_postings r ON r.id = q.raw_posting_id
    WHERE q.first_pass_result IN ('pass', 'ambiguous_forwarded')
    GROUP BY r.location
""")

# Minimal columns, plus the two verdict fields needed to badge each row --
# first_pass_result and location_check_deferred_to_llm (set by
# scripts/promote_ambiguous.py; see below). No gate/verdict *reasons*, no
# salary: this is still the clean stakeholder view, not the technical queue
# FORWARD_QUEUE_SQL already covers -- it just now also surfaces which of the
# two forwarding verdicts produced each row, since 'pass' and
# 'ambiguous_forwarded' used to render identically and were not
# distinguishable in the UI.
#
# WHERE now covers BOTH forwarding verdicts, not just 'ambiguous_forwarded':
# 'pass' rows still need a human approve/reject decision same as ambiguous
# ones (mutations.record_decision doesn't discriminate), so excluding them
# here just meant they never got a decision recorded. Same "opportunities"
# definition as OPPORTUNITIES_BY_SOURCE_SQL / OPPORTUNITIES_BY_LOCATION_SQL
# above.
#
# ORDER BY puts 'pass' rows first (higher confidence -- every hard gate
# cleared, vs. ambiguous_forwarded where at least one gate was undetermined),
# then most-recently-found within each group. `= 'pass'` evaluates to a
# boolean, and DESC sorts TRUE before FALSE, so this needs no CASE.
REVIEW_QUEUE_SQL = text("""
    SELECT q.id                              AS qualified_opportunity_id,
           q.first_pass_result                AS first_pass_result,
           q.location_check_deferred_to_llm   AS location_check_deferred_to_llm,
           COALESCE(c.name, r.company_name)  AS company,
           r.title                           AS title,
           s.name                            AS source,
           r.first_seen_at                   AS date_found,
           r.url                             AS url
    FROM qualified_opportunities q
    JOIN raw_postings r   ON r.id = q.raw_posting_id
    JOIN sources s        ON s.id = r.source_id
    LEFT JOIN companies c ON c.id = r.company_id
    WHERE q.first_pass_result IN ('pass', 'ambiguous_forwarded')
      -- A posting the source stopped returning is a closed/pulled listing in
      -- all but name. Asking a human to review (or approve) it wastes a
      -- decision on something no longer applyable-to, so it's withheld here
      -- rather than shown alongside live rows.
      AND r.is_stale = false
      -- Once a human has approved or rejected an opportunity, it has an
      -- applications row (mutations.record_decision) and must stop
      -- reappearing here as pending.
      AND NOT EXISTS (
          SELECT 1 FROM applications a WHERE a.qualified_opportunity_id = q.id
      )
    ORDER BY (q.first_pass_result = 'pass') DESC, r.first_seen_at DESC
""")


# Name -> statement. app.py's cached loader keys on the NAME, not the statement
# object: a SQLAlchemy TextClause is unhashable, so passing it as a cache
# argument forces Streamlit to skip hashing it (the `_`-prefix convention) --
# and then every no-parameter call collides on an identical empty cache key and
# silently returns whatever the first one cached. That is not hypothetical: it
# happened during development and made the verdict tiles render the
# pipeline_runs frame. A plain string name hashes cleanly and keeps each
# statement's cache entry distinct.
STATEMENTS = {
    "latest_runs":    LATEST_RUNS_SQL,
    "verdict_counts": VERDICT_COUNTS_SQL,
    "reject_reasons": REJECT_REASONS_SQL,
    "forward_queue":  FORWARD_QUEUE_SQL,
    "daily_trend":    DAILY_TREND_SQL,
    "corpus_totals":  CORPUS_TOTALS_SQL,
    "funnel":                    FUNNEL_SQL,
    "opportunities_by_source":   OPPORTUNITIES_BY_SOURCE_SQL,
    "opportunities_by_location": OPPORTUNITIES_BY_LOCATION_SQL,
    "review_queue":              REVIEW_QUEUE_SQL,
}
