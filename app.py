"""
Daily-check dashboard for the opportunity pipeline. Read-only.

Run locally:   streamlit run app.py
Deployed:      Streamlit Community Cloud, main file path = app.py

SCOPE: this answers "did last night's run work, and what is in my queue this
morning". It is deliberately NOT the Phase 2 review/approval UI — no scoring,
no tailoring, no application workflow. Everything here is a SELECT.
"""
import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from queries import STAGE_ORDER, STATEMENTS

# Validated categorical pair for the only genuinely multi-series chart here
# (the trend). Checked with the data-viz validator against the light surface:
# CVD separation ΔE 24.7 protan / 32.7 tritan, normal-vision ΔE 33.6, both
# inside the lightness band and above the chroma floor and 3:1 contrast. Fixed
# assignment — new_postings is always blue, new_opportunities always orange —
# so the colors follow the series, never their rank.
SERIES_BLUE = "#2a78d6"
SERIES_ORANGE = "#eb6834"

TTL = 300  # seconds; a nightly pipeline does not need fresher than this


st.set_page_config(page_title="Pipeline daily check", page_icon="📊", layout="wide")


@st.cache_resource
def get_engine():
    """
    One engine per session, using the same connect args as the pipeline
    (pool_pre_ping, future). Cached with cache_resource because Streamlit
    re-executes this whole module on every interaction — without it, each
    widget click would open a fresh pool against the pooler.

    Reads st.secrets first and falls back to the environment, so one code
    path works both locally and on Streamlit Community Cloud (where there
    is no .env file — the credential arrives through st.secrets).
    """
    url = st.secrets.get("SUPABASE_DB_URL") if hasattr(st, "secrets") else None
    if not url:
        url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        st.error(
            "SUPABASE_DB_URL is not set. Locally: copy "
            "`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and "
            "fill it in (or export the variable). On Streamlit Cloud: paste it "
            "into Settings → Secrets. Use the **Session pooler** URL."
        )
        st.stop()
    return create_engine(url, pool_pre_ping=True, future=True)


@st.cache_data(ttl=TTL)
def load(name, **params):
    """
    Run the named statement and return a DataFrame.

    Keyed on the NAME rather than the statement object on purpose — see the
    comment on queries.STATEMENTS. Passing the TextClause itself would force
    Streamlit to skip hashing it (unhashable), collapsing every no-parameter
    call onto one shared cache entry. `params` is hashed normally, so two
    different :days values cache separately.
    """
    with get_engine().connect() as conn:
        result = conn.execute(STATEMENTS[name], params)
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def queue_table(df, empty_message):
    """Render one forward-queue slice with clickable URLs and tidy columns."""
    if df.empty:
        st.info(empty_message)
        return
    view = df[[
        "title", "company", "source", "location", "url",
        "salary_raw", "salary_estimate_usd_month",
        "is_stale", "stale_days", "fetched_at", "posting_id",
    ]]
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config={
            "title": st.column_config.TextColumn("Title", width="large"),
            "company": st.column_config.TextColumn("Company"),
            "source": st.column_config.TextColumn("Source", width="small"),
            "location": st.column_config.TextColumn("Location"),
            # LinkColumn keeps the row readable — the raw URLs are long enough
            # to blow out the column otherwise.
            "url": st.column_config.LinkColumn("Posting", display_text="open ↗"),
            "salary_raw": st.column_config.TextColumn("Salary (raw)"),
            "salary_estimate_usd_month": st.column_config.NumberColumn(
                "Est. $/mo", format="%.0f"),
            "is_stale": st.column_config.CheckboxColumn("Stale?", width="small"),
            "stale_days": st.column_config.NumberColumn("Stale days", width="small"),
            "fetched_at": st.column_config.DatetimeColumn(
                "Last fetched", format="YYYY-MM-DD HH:mm"),
            "posting_id": st.column_config.NumberColumn("ID", width="small"),
        },
    )


# --- header ----------------------------------------------------------------

left, right = st.columns([4, 1])
with left:
    st.title("Pipeline daily check")
with right:
    if st.button("Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

# --- stage status ----------------------------------------------------------

st.subheader("Last run, by stage")

runs = load("latest_runs")
if runs.empty:
    st.warning("pipeline_runs is empty — no run has ever been recorded.")
else:
    # A stage that has NEVER been recorded is absent from this table entirely,
    # which would silently render as a missing tile — indistinguishable from a
    # stage that simply isn't part of the pipeline. A stage can be in the
    # pipeline's sequence and still have no pipeline_runs row at all, so it
    # is given an explicit "never run" tile rather than being dropped.
    recorded = set(runs["stage"])
    missing = [s for s in STAGE_ORDER if s not in recorded]
    if missing:
        runs = pd.concat([runs, pd.DataFrame([{"stage": s, "status": "never run"}
                                              for s in missing])], ignore_index=True)

    runs["_order"] = runs["stage"].apply(
        lambda s: STAGE_ORDER.index(s) if s in STAGE_ORDER else len(STAGE_ORDER))
    runs = runs.sort_values("_order").drop(columns="_order")

    # Stage cards first: status and recency are what the morning check is
    # actually asking, and they read faster as tiles than as table cells.
    for col, (_, row) in zip(st.columns(len(runs)), runs.iterrows()):
        icon = {"success": "✅", "failed": "🔴",
                "running": "⏳", "never run": "⬜"}.get(row["status"], "❔")
        when = pd.to_datetime(row["started_at"], utc=True) if pd.notna(row["started_at"]) else None
        col.metric(
            label=f"{icon} {row['stage']}",
            value=str(row["status"]),
            delta=when.strftime("%m-%d %H:%M UTC") if when is not None else "—",
            delta_color="off",
        )

    stuck = runs[runs["status"] == "running"]
    if not stuck.empty:
        st.warning(
            f"{len(stuck)} stage(s) still marked `running`. If no pipeline is "
            "actually executing, the owning process was killed before it could "
            "close the row — the next run reconciles it."
        )
    if runs["run_id"].nunique() > 1:
        st.caption(
            "⚠️ Stages below come from different run_ids — the most recent run "
            "did not complete every stage."
        )

    st.dataframe(
        runs.drop(columns=["error_detail"]),
        width="stretch",
        hide_index=True,
        column_config={
            "started_at": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "finished_at": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
        },
    )
    errors = runs[runs["error_detail"].notna()]
    for _, row in errors.iterrows():
        st.caption(f"**{row['stage']}** error: {row['error_detail']}")

# --- verdict breakdown -----------------------------------------------------

st.subheader("Current verdicts")

verdicts = load("verdict_counts")
counts = dict(zip(verdicts["first_pass_result"], verdicts["n"])) if not verdicts.empty else {}
totals = load("corpus_totals")

# Stat tiles, NOT a bar chart. These three counts span roughly 1 / 20 / 7,900 —
# on a shared linear axis the two that actually need watching would be sub-pixel
# next to `excluded`, and a log axis on three bars is worse than no chart. The
# numbers themselves are the finding, so they are shown as numbers.
c1, c2, c3, c4 = st.columns(4)
c1.metric("pass", f"{counts.get('pass', 0):,}")
c2.metric("ambiguous_forwarded", f"{counts.get('ambiguous_forwarded', 0):,}")
c3.metric("excluded", f"{counts.get('excluded', 0):,}")
c4.metric("qualified_opportunities", f"{int(totals['qo_total'][0]):,}" if not totals.empty else "—")

if not totals.empty:
    t = totals.iloc[0]
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("raw_postings", f"{int(t['raw_total']):,}")
    d2.metric("duplicates", f"{int(t['raw_duplicates']):,}")
    d3.metric("stale", f"{int(t['raw_stale']):,}")
    d4.metric(
        "missing embeddings", f"{int(t['missing_embeddings']):,}",
        help="Non-duplicate rows with no embedding. Non-zero usually means "
             "ingest ran but dedupe did not.",
    )

# --- reject reasons --------------------------------------------------------

st.subheader("Why postings are excluded")

reasons = load("reject_reasons")
if reasons.empty:
    st.info("No excluded rows.")
else:
    # Horizontal bars: the labels are long snake_case reason codes, which
    # collide badly as rotated x-axis ticks. One series, so no legend — the
    # heading names it. Sorted by magnitude, which is the question being asked.
    st.bar_chart(
        reasons.set_index("reason")["n"],
        horizontal=True,
        color=SERIES_BLUE,
        height=260,
    )
    st.caption(
        "A posting carrying two reasons counts once against each, so these sum "
        "to more than the excluded total."
    )

# --- queues ----------------------------------------------------------------

queue = load("forward_queue", results=["pass", "ambiguous_forwarded"])
passes = queue[queue["first_pass_result"] == "pass"] if not queue.empty else queue
ambiguous = queue[queue["first_pass_result"] == "ambiguous_forwarded"] if not queue.empty else queue

st.subheader(f"Pass queue ({len(passes)})")
st.caption(
    "Every hard gate cleared. Highest-trust output — and currently the rarest: "
    "a manually confirmed salary is not durable across a prefilter re-run, so a "
    "row resolved by hand can revert to ambiguous overnight."
)
queue_table(passes, "No rows currently at `pass`.")

st.subheader(f"Ambiguous queue ({len(ambiguous)})")
st.caption("No gate failed, but at least one could not be determined. This is the review surface.")

if ambiguous.empty:
    st.info("Ambiguous queue is empty.")
else:
    f1, f2 = st.columns([3, 2])
    sources = sorted(ambiguous["source"].dropna().unique().tolist())
    chosen = f1.multiselect("Source", sources, default=sources)
    stale_choice = f2.radio(
        "Staleness", ["All", "Live only", "Stale only"], horizontal=True,
    )

    filtered = ambiguous[ambiguous["source"].isin(chosen)]
    if stale_choice == "Live only":
        filtered = filtered[~filtered["is_stale"]]
    elif stale_choice == "Stale only":
        filtered = filtered[filtered["is_stale"]]

    st.caption(f"Showing {len(filtered)} of {len(ambiguous)}.")
    queue_table(filtered, "No rows match these filters.")

# --- trend -----------------------------------------------------------------

st.subheader("New rows per day")

trend = load("daily_trend", days=7)
if trend.empty:
    st.info("No trend data.")
else:
    chart = trend.rename(columns={
        "new_postings": "New postings",
        "new_opportunities": "New opportunities",
    }).set_index("day")
    # Two series, same unit (rows/day), so ONE shared axis — never a second
    # y-scale. Days with no ingest come back as an explicit 0 from the SQL, so
    # a failed night reads as a visible trough rather than a missing point.
    st.line_chart(
        chart[["New postings", "New opportunities"]],
        color=[SERIES_BLUE, SERIES_ORANGE],
        height=260,
    )
    st.caption(
        "Counted by first-creation (`first_seen_at` / `created_at`), so "
        "re-fetching or re-evaluating an existing row does not move these. "
        "A flat 0 on both means ingest did not run that day."
    )
