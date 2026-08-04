# job-search-dashboard

A small, read-only Streamlit dashboard for checking a job-search pipeline's
daily results at a glance. The pipeline itself lives in a separate private
repository; this repo holds only the dashboard so it can deploy on Streamlit
Community Cloud's free public-repo tier.

**Everything here is a `SELECT`.** Nothing in this app writes to the database.

## What it shows

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

The app reads four tables — `pipeline_runs`, `raw_postings`,
`qualified_opportunities`, `sources`, and `companies`. All SQL is in
`queries.py`; the column names it depends on are visible there.

## Scope

This is a daily-check tool, not a review/approval UI. There is deliberately no
scoring, no document tailoring, and no application workflow.
