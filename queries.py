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
}
