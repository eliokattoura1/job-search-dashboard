"""
Dashboard for the opportunity pipeline. Read-only.

Run locally:   streamlit run app.py
Deployed:      Streamlit Community Cloud, main file path = app.py

Two audiences, two groups of tabs:
  * The first 7 tabs (Funnel through Applications) are stakeholder-facing —
    what the search has found, in plain language. No run status, no error
    detail, no connector/gate internals. Review Queue is the one exception
    to "no workflow": it has an Approve/Reject step (see mutations.py).
  * "Pipeline Status" (last) is the original daily-check tool: did last
    night's run work, and what is in the technical queue. Unchanged from
    before the stakeholder tabs were added.

SCOPE: no scoring, no tailoring. All reads go through queries.py
(SELECT-only); the only writes are the two INSERTs in mutations.py, behind
the Review Queue tab's Approve/Reject buttons.
"""
import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

import mutations
import regions
import theme
from queries import REASON_LABELS, SOURCE_DISPLAY_NAMES, STAGE_ORDER, STATEMENTS

# Validated categorical pair for the only genuinely multi-series chart here
# (the trend, in the Pipeline Status tab). Checked with the data-viz
# validator against the light surface: CVD separation ΔE 24.7 protan / 32.7
# tritan, normal-vision ΔE 33.6, both inside the lightness band and above the
# chroma floor and 3:1 contrast. Fixed assignment — new_postings is always
# blue, new_opportunities always orange — so the colors follow the series,
# never their rank.
SERIES_BLUE = "#2a78d6"
SERIES_ORANGE = "#eb6834"

TTL = 300  # seconds; a nightly pipeline does not need fresher than this


st.set_page_config(page_title="Opportunity Pipeline", page_icon="📊", layout="wide")


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


def source_label(name):
    """Clean display name for a source, falling back to a title-cased raw
    name so a source added later never renders as an empty/blank label."""
    if name is None:
        return "Unknown"
    return SOURCE_DISPLAY_NAMES.get(name, str(name).title())


def handle_decision(qualified_opportunity_id, status, verb):
    """Record one approve/reject click and refresh the queue."""
    actor = mutations.get_actor(st)
    recorded = mutations.record_decision(get_engine(), qualified_opportunity_id, status, actor)
    st.cache_data.clear()
    if recorded:
        st.toast(f"Marked {verb} by {actor}.")
    else:
        st.warning("Already actioned by someone else — refreshing.")
    st.rerun()


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


# --- theme ---------------------------------------------------------------

# Read BEFORE the toggle widget below is created: on the rerun a toggle click
# triggers, session_state already holds the new value, so the CSS injected
# here always matches what the toggle will show a few lines down — no lag,
# no separate "apply" step. Defaults to light, per spec, on a session that
# has never touched the toggle.
dark_mode = st.session_state.get("dark_mode", False)
theme.inject(dark_mode)

# --- header ----------------------------------------------------------------

left, mid, right = st.columns([4, 1, 1])
with left:
    st.title("Opportunity Pipeline")
with mid:
    st.toggle("Dark mode", key="dark_mode")
with right:
    if st.button("Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

(
    tab_funnel,
    tab_queue,
    tab_source,
    tab_region,
    tab_reasons,
    tab_qualified,
    tab_applications,
    tab_status,
) = st.tabs([
    "Funnel",
    "Review Queue",
    "Opportunities by Source",
    "Opportunities by Region",
    "Rejection Reasons",
    "Qualified Matches",
    "Applications",
    "Pipeline Status",
])

# =========================================================================
# Funnel
# =========================================================================
with tab_funnel:
    st.subheader("Search funnel")

    funnel = load("funnel")
    if funnel.empty:
        st.info("No data yet.")
    else:
        f = funnel.iloc[0]
        ingested = int(f["ingested"]) if pd.notna(f["ingested"]) else 0
        prefiltered = int(f["prefiltered"]) if pd.notna(f["prefiltered"]) else 0
        qualified = int(f["qualified"]) if pd.notna(f["qualified"]) else 0
        applications_submitted = (
            int(f["applications_submitted"]) if pd.notna(f["applications_submitted"]) else 0
        )

        # Expected, not a warning: prefilter re-evaluates every non-duplicate
        # posting each run, not just the ones ingested that night, so this
        # can legitimately read higher than Ingested. Reusing .jsd-count-note
        # (muted token, small type) rather than a new class — same "small
        # helper text" role the Review Queue tab already uses it for.
        st.markdown(
            '<p class="jsd-count-note">Prefiltered includes postings '
            're-evaluated from prior nights, not just last night’s new '
            'ingest — so this number can be higher than Ingested.</p>',
            unsafe_allow_html=True,
        )

        # Qualified/Applications Submitted show "Coming soon" rather than a
        # bare 0 when nothing has moved through that stage yet — a 0 here
        # would read as "the search tried and found nothing", when the truer
        # statement is "this stage isn't running yet". Ingested/Prefiltered
        # always show the real number, including a real 0, since that is
        # never true of them once the pipeline has run at all. The muted
        # ("Coming soon") flag drives styling only — same card shape either
        # way, see theme.render_funnel.
        theme.render_funnel([
            ("Ingested", f"{ingested:,}", False),
            ("Prefiltered", f"{prefiltered:,}", False),
            ("Qualified", f"{qualified:,}" if qualified else "Coming soon", not qualified),
            ("Applications Submitted",
             f"{applications_submitted:,}" if applications_submitted else "Coming soon",
             not applications_submitted),
        ])

# =========================================================================
# Review Queue
# =========================================================================
with tab_queue:
    st.subheader("Review queue")

    review_queue = load("review_queue")
    if review_queue.empty:
        st.info("Nothing in the review queue right now.")
    else:
        st.markdown(
            f'<p class="jsd-count-note"><span class="jsd-count-badge">'
            f'{len(review_queue):,}</span> awaiting review</p>',
            unsafe_allow_html=True,
        )
        theme.render_table(
            [
                {
                    "company": row["company"],
                    "title": row["title"],
                    "source": source_label(row["source"]),
                    "date_found": pd.Timestamp(row["date_found"]).strftime("%Y-%m-%d"),
                    "url": row["url"],
                }
                for row in review_queue.to_dict("records")
            ],
            columns=[
                ("company", "Company", {}),
                ("title", "Title", {}),
                ("source", "Source", {}),
                ("date_found", "Date Found", {"mono": True}),
                ("url", "View Posting", {"link": True}),
            ],
        )

        # Select-then-act rather than a button per row: theme.render_table is
        # plain HTML (see its docstring — deliberate, for the custom
        # typography), and an HTML <button> inside unsafe_allow_html markup
        # can't trigger a Streamlit callback. This keeps the styled table
        # untouched and adds one real Streamlit widget below it instead.
        st.markdown("##### Record a decision")
        by_id = {row["qualified_opportunity_id"]: row for row in review_queue.to_dict("records")}
        selected_id = st.selectbox(
            "Opportunity",
            options=list(by_id.keys()),
            format_func=lambda qid: f'{by_id[qid]["company"]} — {by_id[qid]["title"]}',
            key="review_queue_selected_id",
        )
        b1, b2 = st.columns(2)
        if b1.button("Approve", width="stretch", key="review_queue_approve"):
            handle_decision(selected_id, mutations.STATUS_APPROVED, "approved")
        if b2.button("Reject", width="stretch", key="review_queue_reject"):
            handle_decision(selected_id, mutations.STATUS_REJECTED, "rejected")

# =========================================================================
# Opportunities by Source
# =========================================================================
with tab_source:
    st.subheader("Opportunities by source")

    by_source = load("opportunities_by_source")
    if by_source.empty:
        st.info("No opportunities found yet.")
    else:
        # Already ranked descending in SQL.
        theme.render_table(
            [
                {"source": source_label(row["source"]), "n": f"{row['n']:,}"}
                for row in by_source.to_dict("records")
            ],
            columns=[
                ("source", "Source", {}),
                ("n", "Opportunities Found", {"mono": True, "accent": "signal"}),
            ],
        )

# =========================================================================
# Opportunities by Region
# =========================================================================
with tab_region:
    st.subheader("Opportunities by region")

    by_location = load("opportunities_by_location")
    if by_location.empty:
        st.info("No opportunities found yet.")
    else:
        # Bucketing logic reused as-is from the pipeline repo's
        # dashboard/regions.py (shipped 2026-08-10) — not reimplemented here.
        binned = regions.add_area_column(by_location, source_column="location", target_column="Region")
        by_region = binned.groupby("Region", as_index=False)["n"].sum()
        ordered = (
            by_region.set_index("Region")
                     .reindex(regions.BUCKET_ORDER, fill_value=0)["n"]
                     .rename("Opportunities Found")
                     .reset_index()
        )
        theme.render_table(
            [
                {"region": row["Region"], "n": f"{row['Opportunities Found']:,}"}
                for row in ordered.to_dict("records")
            ],
            columns=[
                ("region", "Region", {}),
                ("n", "Opportunities Found", {"mono": True, "accent": "signal"}),
            ],
        )

# =========================================================================
# Rejection Reasons
# =========================================================================
with tab_reasons:
    st.subheader("Rejection reasons")

    reasons = load("reject_reasons")
    if reasons.empty:
        st.info("No rejected postings yet.")
    else:
        # Already ranked descending in SQL. Unrecognized codes fall back to
        # the raw code rather than disappearing, so a new reason added to
        # the pipeline's vocabulary is still visible here before its label
        # is added to queries.REASON_LABELS. Neutral ink, not signal/review —
        # a rejection is neither "found" nor "pending", so it gets no accent.
        theme.render_table(
            [
                {"reason": REASON_LABELS.get(row["reason"], row["reason"]),
                 "n": f"{row['n']:,}"}
                for row in reasons.to_dict("records")
            ],
            columns=[
                ("reason", "Reason", {}),
                ("n", "Count", {"mono": True}),
            ],
        )

# =========================================================================
# Qualified Matches — stub. Deep qualification scoring (qualified_
# opportunities.deep_review_score / score_breakdown / classification) isn't
# populated by any pipeline stage yet, so there is nothing real to show.
# Structured as its own tab now so filling it in later is a content change
# here, not a restructuring of the tab layout.
# =========================================================================
with tab_qualified:
    st.subheader("Qualified matches")
    st.info("Deep qualification scoring is in development.")

# =========================================================================
# Applications — stub, same reasoning as Qualified Matches. The
# `applications` table exists in the schema but nothing writes to it yet.
# =========================================================================
with tab_applications:
    st.subheader("Applications")
    st.info("Application tracking will appear here once qualification and tailoring are live.")

# =========================================================================
# Pipeline Status — the original daily-check content, unchanged, now living
# in its own tab instead of the whole page.
# =========================================================================
with tab_status:
    # --- stage status ----------------------------------------------------

    st.subheader("Last run, by stage")

    runs = load("latest_runs")
    if runs.empty:
        st.warning("pipeline_runs is empty — no run has ever been recorded.")
    else:
        # A stage that has NEVER been recorded is absent from this table
        # entirely, which would silently render as a missing tile —
        # indistinguishable from a stage that simply isn't part of the
        # pipeline. Any stage in STAGE_ORDER with no pipeline_runs row is
        # therefore given an explicit "never run" tile rather than being
        # dropped — a newly added stage sits in exactly that state until the
        # first run that executes it.
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

    # --- verdict breakdown -------------------------------------------------

    st.subheader("Current verdicts")

    verdicts = load("verdict_counts")
    counts = dict(zip(verdicts["first_pass_result"], verdicts["n"])) if not verdicts.empty else {}
    totals = load("corpus_totals")

    # Stat tiles, NOT a bar chart. These three counts span roughly 1 / 20 /
    # 7,900 — on a shared linear axis the two that actually need watching
    # would be sub-pixel next to `excluded`, and a log axis on three bars is
    # worse than no chart. The numbers themselves are the finding, so they
    # are shown as numbers.
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

    # --- reject reasons ------------------------------------------------------

    st.subheader("Why postings are excluded")

    reasons = load("reject_reasons")
    if reasons.empty:
        st.info("No excluded rows.")
    else:
        # Horizontal bars: the labels are long snake_case reason codes, which
        # collide badly as rotated x-axis ticks. One series, so no legend —
        # the heading names it. Sorted by magnitude, which is the question
        # being asked.
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

    # --- queues --------------------------------------------------------------

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
