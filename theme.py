"""
Design tokens and CSS injection for the dashboard's visual theme.

WHAT LIVES HERE
  * LIGHT / DARK — the two token sets (design spec, 2026-08-11).
  * inject(dark) — writes ONE <style> block per rerun. Component CSS is
    written once, in terms of `var(--token)`; only the :root VALUES change
    between inject(False) and inject(True). This is deliberate (see the
    implementation note below) — duplicating the component rules per theme
    would mean every future style change has to be made twice and can drift.
  * render_table / render_funnel — small HTML-building helpers so app.py
    doesn't hand-assemble markup inline. Every text value passed through
    these is html.escape()'d before interpolation: this module renders raw
    HTML via st.markdown(unsafe_allow_html=True), so an unescaped "&" in a
    job title (seen in real data — "AI & Emerging Technology") would corrupt
    the markup, and an unescaped "<"/">" would inject arbitrary HTML. Escape
    at the point of interpolation, not by trusting the caller.

WHY CSS VARIABLES, NOT DUPLICATED RULES
Streamlit reruns this whole module on every interaction (a tab click, the
dark-mode toggle, Refresh). Re-injecting a full stylesheet every rerun is
required either way — Streamlit has no persistent <head> a library can write
to once — but the CONTENT of that stylesheet only needs the seven --token
values to change, never the ~150 lines of rules that reference them. Two
complete stylesheets (one per theme) would be the same 150 lines twice, and
every future tweak would need to be applied in both places or the two modes
silently drift apart.

STREAMLIT CSS TARGETING — VERSION FRAGILITY, FLAGGED HERE ONCE
Everything below targets `data-testid`/`data-baseweb` attributes rather than
Streamlit's generated class names (those are content-hashed and change on
every Streamlit release; the testids have been stable across many releases
and are what Streamlit's own end-to-end tests key on). That's the more
stable choice available, not an immune one: requirements.txt pins
`streamlit>=1.35` with no upper bound, so a materially newer minor version on
Streamlit Community Cloud than the one this was built/tested against
(1.57.0, installed locally) could still rename or restructure one of these
attributes. Verified against 1.57.0 by running the real app (AppTest); not
verified against whatever Cloud actually resolves at deploy time.

Three rules below are BEST-EFFORT, specifically flagged as lower-confidence
than the rest: the dark-mode toggle's switch-track recolor and the st.info
alert-box recolor (both target baseweb/Streamlit internal DOM structure that
this session could not visually confirm without a browser), and the
narrow-viewport funnel stacking (written to a sensible breakpoint, not
visually verified — see the report for what AppTest can and can't check).
"""
import html

import streamlit as st

LIGHT = {
    "bg": "#FCFCFA",
    "surface": "#FFFFFF",
    "ink": "#1C1E21",
    "muted": "#6B7280",
    "signal": "#2D6A4F",
    "review": "#B08830",
    "hairline": "#E4E2DC",
}

DARK = {
    "bg": "#14161A",
    "surface": "#1C1F24",
    "ink": "#F2F1ED",
    "muted": "#9CA3AF",
    "signal": "#4E9B76",
    "review": "#D9A64E",
    "hairline": "#2C2F35",
}

FONT_IMPORT_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&"
    "family=Inter:wght@400;500;600;700&"
    "family=IBM+Plex+Mono:wght@400;500;600&"
    "display=swap"
)


def inject(dark):
    """Write the theme <style> block for this rerun. Call once, near the top
    of the script, before any content that should carry the theme."""
    tokens = DARK if dark else LIGHT
    root_vars = "\n".join(f"  --{k}: {v};" for k, v in tokens.items())

    st.markdown(f"""
<style>
@import url('{FONT_IMPORT_URL}');

:root {{
{root_vars}
  --radius: 8px;
}}

/* ---------- reduced motion: honored globally, before anything else adds a
   transition below. Scoped to `transition`/`animation` only — this is the
   one place a blanket `*` selector is the correct call, since turning off
   motion for every element is exactly what the media query means. ---------- */
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}

/* ---------- base: background + body/document text ---------- */
html, body {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}}
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
  background: var(--bg) !important;
}}
[data-testid="stAppViewContainer"] {{
  color: var(--ink);
}}

/* Display font on section headers only (st.title / st.subheader render as
   h1/h2/h3) — "used sparingly, not on every label" per spec, so this is the
   ONLY place Fraunces is applied outside the funnel numerals below. */
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3 {{
  font-family: 'Fraunces', Georgia, serif;
  font-weight: 500;
  color: var(--ink);
}}

[data-testid="stCaptionContainer"], .jsd-muted {{
  color: var(--muted) !important;
}}

/* ---------- tab strip: quiet pill nav, no default blue underline ---------- */
[data-baseweb="tab-list"] {{
  gap: 6px;
  background: transparent;
  border-bottom: 1px solid var(--hairline) !important;
  padding-bottom: 8px;
}}
[data-baseweb="tab-highlight"] {{ background: transparent !important; }}
[data-baseweb="tab-border"] {{ background: transparent !important; }}
[data-baseweb="tab"] {{
  height: auto;
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--hairline);
  background: transparent;
  font-family: 'Inter', sans-serif;
  font-weight: 500;
  font-size: 0.875rem;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}}
[data-baseweb="tab"] p {{
  color: var(--muted);
  font-family: inherit;
  font-weight: inherit;
}}
[data-baseweb="tab"][aria-selected="true"] {{
  background: var(--surface);
  border-color: var(--ink);
}}
[data-baseweb="tab"][aria-selected="true"] p {{
  color: var(--ink);
}}

/* ---------- info/empty-state boxes (st.info, used by every tab's empty
   state and both stub tabs) — best-effort, see module docstring. ---------- */
[data-testid="stAlert"] {{
  background: var(--surface) !important;
  border: 1px solid var(--hairline) !important;
  border-radius: var(--radius) !important;
  color: var(--ink) !important;
}}
[data-testid="stAlert"] p {{
  color: var(--ink) !important;
  font-family: 'Inter', sans-serif;
}}

/* ---------- dark-mode toggle: best-effort recolor, see module docstring ---------- */
[data-testid="stToggle"] label div[data-baseweb="toggle"] {{
  background: var(--hairline) !important;
}}
[data-testid="stToggle"] label div[data-baseweb="toggle"][aria-checked="true"] {{
  background: var(--ink) !important;
}}

/* ---------- generic card (funnel stages today; reusable) ---------- */
.jsd-card {{
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: 20px 16px;
}}

/* ---------- funnel: signature horizontal stage row ---------- */
.jsd-funnel {{
  display: flex;
  align-items: center;
  gap: 0;
  margin: 4px 0 28px 0;
}}
.jsd-funnel-card {{
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
}}
.jsd-funnel-number {{
  font-family: 'Fraunces', Georgia, serif;
  font-weight: 500;
  font-size: 2.5rem;
  line-height: 1;
  color: var(--signal);
  font-variant-numeric: tabular-nums;
}}
.jsd-funnel-number.is-muted {{
  color: var(--muted);
  font-size: 1.375rem;
  font-family: 'Inter', sans-serif;
  font-weight: 500;
}}
.jsd-funnel-label {{
  font-family: 'Inter', sans-serif;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--muted);
}}
.jsd-funnel-connector {{
  flex: 0 0 44px;
  align-self: center;
  border-top: 1px solid var(--hairline);
  height: 0;
  position: relative;
}}
.jsd-funnel-connector::after {{
  content: "";
  position: absolute;
  right: -1px;
  top: -4px;
  width: 7px;
  height: 7px;
  border-top: 1px solid var(--hairline);
  border-right: 1px solid var(--hairline);
  transform: rotate(45deg);
}}
@media (max-width: 640px) {{
  .jsd-funnel {{ flex-direction: column; align-items: stretch; gap: 12px; }}
  .jsd-funnel-connector {{
    flex: 0 0 20px;
    align-self: center;
    width: 0;
    height: 20px;
    border-top: none;
    border-left: 1px solid var(--hairline);
  }}
  .jsd-funnel-connector::after {{
    right: auto;
    left: -4px;
    top: auto;
    bottom: -1px;
    transform: rotate(135deg);
  }}
}}

/* ---------- plain tables (Source / Region / Rejection Reasons / Review Queue) ---------- */
.jsd-table-wrap {{
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  overflow: auto;
  margin: 4px 0 8px 0;
}}
.jsd-table {{
  width: 100%;
  border-collapse: collapse;
  font-family: 'Inter', sans-serif;
  font-size: 0.875rem;
  background: var(--surface);
}}
.jsd-table th {{
  text-align: left;
  font-family: 'Inter', sans-serif;
  font-weight: 600;
  font-size: 0.6875rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 10px 16px;
  border-bottom: 1px solid var(--hairline);
  white-space: nowrap;
}}
.jsd-table td {{
  padding: 10px 16px;
  border-bottom: 1px solid var(--hairline);
  color: var(--ink);
}}
.jsd-table tr:last-child td {{ border-bottom: none; }}
.jsd-table-num {{
  font-family: 'IBM Plex Mono', 'Courier New', monospace;
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}}
.jsd-signal {{ color: var(--signal); }}
.jsd-review {{ color: var(--review); }}
/* Small inline count note (e.g. "N awaiting review") — review-gold is the
   "pending" token, so this is its one deliberate use outside a table cell. */
.jsd-count-badge {{
  font-family: 'IBM Plex Mono', 'Courier New', monospace;
  font-variant-numeric: tabular-nums;
  color: var(--review);
  font-weight: 600;
}}
.jsd-count-note {{
  font-family: 'Inter', sans-serif;
  font-size: 0.875rem;
  color: var(--muted);
  margin: -4px 0 12px 0;
}}
.jsd-link {{
  color: var(--ink);
  text-decoration: none;
  border-bottom: 1px solid var(--hairline);
  font-family: 'Inter', sans-serif;
  font-size: 0.8125rem;
  white-space: nowrap;
}}
.jsd-link:hover {{ border-bottom-color: var(--ink); }}
</style>
""", unsafe_allow_html=True)


def _cell(value, *, mono=False, accent=None, link=False):
    """One <td> for render_table. `value` is escaped here — see module note."""
    classes = []
    if mono:
        classes.append("jsd-table-num")
    if accent:
        classes.append(f"jsd-{accent}")
    class_attr = f' class="{" ".join(classes)}"' if classes else ""

    if link:
        if not value:
            return f"<td{class_attr}></td>"
        safe_url = html.escape(str(value), quote=True)
        return f'<td{class_attr}><a class="jsd-link" href="{safe_url}" target="_blank" rel="noopener">open ↗</a></td>'

    text = "" if value is None else html.escape(str(value))
    return f"<td{class_attr}>{text}</td>"


def render_table(rows, columns):
    """
    rows: list of dicts. columns: list of (key, header, opts) tuples, where
    opts is a dict that may set mono=True (IBM Plex Mono, right-aligned),
    accent="signal"|"review", or link=True (renders `key`'s value as a
    clickable "open ↗", used for the Review Queue's posting URL).

    Deliberately plain HTML + CSS, not st.dataframe: st.dataframe's grid
    (glide-data-grid) renders cell contents on a <canvas>, which does not
    accept CSS font-family/color overrides at all — the custom typography
    this theme exists for would silently not apply to a single cell. See the
    report for the full explanation; this is the adaptation it produced.
    """
    head = "".join(f"<th>{html.escape(header)}</th>" for _, header, _ in columns)
    body_rows = []
    for row in rows:
        cells = "".join(
            _cell(row.get(key), **opts) for key, _, opts in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")
    table_html = (
        '<div class="jsd-table-wrap"><table class="jsd-table">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def render_funnel(stages):
    """
    stages: list of (label, display_value, is_muted) tuples, in display
    order. is_muted=True renders the "Coming soon" treatment — same
    .jsd-card shape, muted text, smaller non-numeral type — never a
    different card structure, per spec.
    """
    parts = ['<div class="jsd-funnel">']
    for i, (label, value, is_muted) in enumerate(stages):
        if i:
            parts.append('<div class="jsd-funnel-connector"></div>')
        number_class = "jsd-funnel-number is-muted" if is_muted else "jsd-funnel-number"
        parts.append(
            '<div class="jsd-funnel-card jsd-card">'
            f'<div class="{number_class}">{html.escape(str(value))}</div>'
            f'<div class="jsd-funnel-label">{html.escape(str(label))}</div>'
            "</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
