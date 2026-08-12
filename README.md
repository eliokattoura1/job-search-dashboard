# job-search-dashboard

A small Streamlit dashboard for a job-search pipeline, with a lightweight
human approve/reject step on the Review Queue tab. The pipeline itself lives
in a separate private repository; this repo holds only the dashboard so it
can deploy on Streamlit Community Cloud's free public-repo tier.

All reads go through `queries.py`, which is `SELECT`-only. The only writes
are the two `INSERT`s in `mutations.py`, behind the Review Queue tab's
Approve/Reject buttons.

## Theme

Design tokens (light/dark colors), the Fraunces/Inter/IBM Plex Mono type
system, and the CSS for the tab nav, cards, and plain tables all live in
`theme.py` — one file, one `inject(dark: bool)` call per rerun. A dark-mode
toggle in the header switches it live via `st.session_state`; light is the
default on load. See `theme.py`'s own docstring for which CSS rules are
solid (target Streamlit's `data-testid`/`data-baseweb` attributes) versus
best-effort (a few spots — the toggle switch itself, `st.info` boxes — touch
Streamlit/baseweb internals this session couldn't visually confirm without a
browser).

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
  currently awaiting human review. Stale postings
  (`raw_postings.is_stale`) are excluded outright. Below the table, a
  select-then-act control (pick an opportunity, then Approve/Reject) records
  the decision — see "Review workflow" below.
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

## Review workflow

The Review Queue tab's table (`theme.render_table`) is deliberately plain
HTML/CSS for typography control, which can't host live `st.button` widgets
per row — so instead of buttons inline in the table, there's a
select-then-act control underneath it: pick an opportunity from a dropdown,
then click **Approve** or **Reject**.

Either action inserts one row into `applications`
(`qualified_opportunity_id`, `status`, `approved_by`, `approved_at`) — this
only records the human decision. `cv_variant_used` and `cv_file_url` stay
`NULL` until the tailoring engine (brief §10) exists and writes them.
Rejections use `status = 'rejected_by_human'` (the actual
`application_status_enum` value — not `'rejected'`); there's no
rejection-reason field, since `applications` has no column for one.

`approved_by` is the Streamlit-authenticated user's email if OIDC viewer
auth is configured for this deployment (`st.user.email`), otherwise the
static placeholder `"elio"` — this deployment currently has no auth
configured, so every decision is attributed to that placeholder.

Once a `qualified_opportunity_id` has an `applications` row, `review_queue`
stops returning it, so it drops out of the dropdown and the table on the
next refresh instead of reappearing as pending. The `UNIQUE` constraint on
`applications.qualified_opportunity_id` (schema.sql:418) makes
double-actioning a no-op — a repeat click surfaces a warning instead of
failing.

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
`sources`, `companies`, and `applications`. All read SQL is in `queries.py`;
the only writes are the two `INSERT`s in `mutations.py`, whose columns match
`application_status_enum` / `response_status_enum` from the pipeline's
`schema.sql`.

## Scope

This is a daily-check tool with a lightweight human approve/reject step —
not the full Phase 2 review UI. There is still no scoring and no document
tailoring; this app never writes `cv_variant_used` or `cv_file_url`.
