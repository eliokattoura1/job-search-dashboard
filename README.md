# job-search-dashboard

A small, read-only Streamlit dashboard for a job-search pipeline. The
pipeline itself lives in a separate private repository; this repo holds only
the dashboard so it can deploy on Streamlit Community Cloud's free
public-repo tier.

**Everything here is a `SELECT`.** Nothing in this app writes to the database.

Two groups of tabs, for two different readers:

## Stakeholder-facing tabs (Funnel, Opportunities by Source, Opportunities by
Region, Rejection Reasons, Review Queue, Qualified Matches, Applications)

Plain counts and tables, no dev/ops language, no run-status or connector
detail — what the search has found, not how the pipeline is running.

- **Funnel** — Ingested → Prefiltered → Qualified → Applications Submitted.
  The latter two show "Coming soon" instead of a bare `0` until those stages
  actually populate `qualified_opportunities.deep_review_score` /
  `applications`, which nothing does yet.
- **Opportunities by Source** — postings that cleared prefilter (not raw
  ingested volume), by source, with clean display names (e.g. "RemoteOK",
  not `remoteok`).
- **Opportunities by Region** — same postings, grouped using the area-bucket
  logic shipped 2026-08-10 in the pipeline repo's `dashboard/regions.py`
  (copied here verbatim, not reimplemented — see `regions.py`).
- **Rejection Reasons** — prefilter's fixed reason-code vocabulary, relabeled
  into plain language (`role_not_in_taxonomy` → "Not a targeted role type",
  etc. — see `queries.REASON_LABELS`).
- **Review Queue** — company, title, source, and date found for postings
  currently awaiting human review. No ids, no gate/verdict columns.
- **Qualified Matches**, **Applications** — placeholders ("Coming soon")
  until deep qualification scoring and application tracking are built.

## Pipeline Status tab (technical / daily-check)

The original single-page dashboard, unchanged, now living in its own tab:

- **Last run, by stage** — the most recent `pipeline_runs` row per stage, with
  status and timestamp. A stage that has never been recorded gets an explicit
  "never run" tile rather than silently vanishing, and stages coming from
  different run ids are called out (which is what a partially-failed run looks
  like).
- **Current verdicts** — counts of `pass` / `ambiguous_forwarded` / `excluded`,
  plus corpus totals (rows, duplicates, stale, missing embeddings).
- **Why postings are excluded** — reject-reason frequency, ranked.
- **Pass and ambiguous queues** — the actual review surface: title, company,
  source, location, clickable posting URL, salary, and staleness, filterable by
  source and staleness.
- **New rows per day** — a 7-day trend. The day axis is generated in SQL, so a
  day with no ingest shows as an explicit `0` trough instead of disappearing
  from the chart.

## Setup

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and paste your connection string
streamlit run app.py
```

`.streamlit/secrets.toml` is gitignored and must never be committed. The app
reads `st.secrets` first and falls back to a `SUPABASE_DB_URL` environment
variable, so the same code path works locally and when deployed.

## Deploying to Streamlit Community Cloud

Point a new app at this repo with **main file path `app.py`**, then paste the
same `SUPABASE_DB_URL` key into the app's *Settings → Secrets* box — Community
Cloud exposes it as `st.secrets` exactly like a local file.

Use the **session pooler** connection string, not the direct connection: direct
connections are IPv4-limited on Supabase's free tier and are not reachable from
Community Cloud's runners. See `.streamlit/secrets.toml.example` for the exact
format.

## Expected schema

The app reads `pipeline_runs`, `raw_postings`, `qualified_opportunities`,
`sources`, `companies`, and `applications` (Funnel tab only, currently always
empty). All SQL is in `queries.py`; the column names it depends on are
visible there.

## Scope

This is a daily-check tool, not a review/approval UI. There is deliberately no
scoring, no document tailoring, and no application workflow.
