"""
May Long Weekend Weather Dashboard – Calgary International Airport
Victoria Day weekends (Sat–Mon) 2006–2025.
Data cached to may_long_data.csv after first run.
"""

import os
import requests
import pandas as pd
from io import StringIO
from datetime import date, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Config ────────────────────────────────────────────────────────────────────

CACHE_FILE = "may_long_data.csv"
BASE_URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"
YEARS = list(range(2006, 2026))
# Two consecutive stations at Calgary International Airport:
#   2205  → CALGARY INT'L A  (daily data through 2012-07-11)
#   50430 → CALGARY INTL A   (daily data 2012-02 onward)
STATION = {y: (2205 if y <= 2012 else 50430) for y in YEARS}

DAY_ORDER = ["saturday", "sunday", "monday"]
DAY_LABELS = {"saturday": "Saturday", "sunday": "Sunday", "monday": "Monday"}
DAY_COLORS = {"saturday": "#4C78A8", "sunday": "#F58518", "monday": "#54A24B"}

# ── 1. Victoria Day dates ─────────────────────────────────────────────────────


def victoria_day(year: int) -> date:
    may25 = date(year, 5, 25)
    return may25 - timedelta(days=may25.weekday())


may_long_weekends = {}
for y in YEARS:
    mon = victoria_day(y)
    may_long_weekends[y] = {
        "saturday": mon - timedelta(days=2),
        "sunday": mon - timedelta(days=1),
        "monday": mon,
    }

# ── 2. Load or scrape data ────────────────────────────────────────────────────

TARGET_COLS = {
    "max_temp": "Max Temp (°C)",
    "min_temp": "Min Temp (°C)",
    "total_rain": "Total Rain (mm)",
    "total_snow": "Total Snow (cm)",
}


def coerce_numeric(val) -> float:
    if isinstance(val, str) and val.strip().upper() in ("T", "TT"):
        return 0.01
    try:
        return float(val)
    except (ValueError, TypeError):
        return float("nan")


if os.path.exists(CACHE_FILE):
    print(f"Loading cached data from {CACHE_FILE}")
    weather = pd.read_csv(CACHE_FILE)
    weather["date"] = pd.to_datetime(weather["date"]).dt.date
else:
    print("Scraping from Environment Canada…")
    records = []
    for year in YEARS:
        print(f"  {year}…", end=" ", flush=True)
        try:
            r = requests.get(
                BASE_URL,
                params=dict(
                    format="csv",
                    stationID=STATION[year],
                    Year=year,
                    Month=5,
                    Day=1,
                    timeframe=2,
                    submit="Download Data",
                ),
                timeout=30,
            )
            r.raise_for_status()
            lines = r.text.splitlines()
            header_idx = next(i for i, ln in enumerate(lines) if "Date/Time" in ln)
            df = pd.read_csv(StringIO("\n".join(lines[header_idx:])))
            df.columns = [c.strip() for c in df.columns]
            date_col = next(c for c in df.columns if "Date" in c)
            df["_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
            df = df.dropna(subset=["_date"])

            weekend_dates = set(may_long_weekends[year].values())
            day_label = {v: k for k, v in may_long_weekends[year].items()}
            matched = df[df["_date"].isin(weekend_dates)]

            for _, row in matched.iterrows():
                rec = {
                    "year": year,
                    "date": row["_date"],
                    "day_name": day_label.get(row["_date"], "?"),
                }
                for key, col in TARGET_COLS.items():
                    rec[key] = coerce_numeric(row.get(col, float("nan")))
                records.append(rec)
            print(f"OK ({len(matched)} days)")
        except Exception as exc:
            print(f"FAILED: {exc}")

    weather = pd.DataFrame(records).sort_values(["year", "date"]).reset_index(drop=True)
    weather.to_csv(CACHE_FILE, index=False)
    print(f"Saved to {CACHE_FILE}\n")

# Weekend-level summary (for the 3 overview plots)
summary = (
    weather.groupby("year")
    .agg(
        max_temp_high=("max_temp", "max"),
        min_temp_low=("min_temp", "min"),
        total_rain=("total_rain", "sum"),
        total_snow=("total_snow", "sum"),
    )
    .reset_index()
)

# ── 3. Weather emoji per day ──────────────────────────────────────────────────


def weather_emoji(row) -> str:
    snow = 0 if pd.isna(row["total_snow"]) else row["total_snow"]
    rain = 0 if pd.isna(row["total_rain"]) else row["total_rain"]
    mx = row["max_temp"] if not pd.isna(row["max_temp"]) else 10
    if snow > 2:
        return "❄️"
    if snow > 0.1 and rain > 1:
        return "🌨️"
    if rain > 15:
        return "⛈️"
    if rain > 3:
        return "🌧️"
    if rain > 0.1:
        return "🌦️"
    if mx >= 23:
        return "☀️"
    if mx >= 16:
        return "🌤️"
    return "⛅"


weather["emoji"] = weather.apply(weather_emoji, axis=1)

# ── 4. Temperature colour ramp (blue → orange → red) ─────────────────────────


def temp_color(temp) -> str:
    """Map temperature (°C) to a hex colour: cold=blue, warm=orange, hot=red."""
    if pd.isna(temp):
        return "rgba(180,180,180,0.4)"
    t = max(0.0, min(1.0, (temp - (-5)) / 35.0))  # -5°C → 0, 30°C → 1
    r = int(70 + t * (220 - 70))
    g = int(130 - t * (130 - 60))
    b = int(220 - t * (220 - 50))
    return f"rgb({r},{g},{b})"


# ── 5. Build figure ───────────────────────────────────────────────────────────
#
# Layout: 3 rows × 2 cols
#   Left col  (col 1): temp bars | snow bars | rain bars  — shared x-axis (years)
#   Right col (col 2): year-detail chart, spans all 3 rows

fig = make_subplots(
    rows=3,
    cols=2,
    specs=[
        [{}, {"rowspan": 3}],
        [{}, None],
        [{}, None],
    ],
    subplot_titles=[
        "🌡️  Temperature Range (°C)",
        "",  # rowspan placeholder — empty, positioned top-right
        "❄️  Total Snow (cm)",
        "🌧️  Total Rain (mm)",
    ],
    shared_xaxes=True,  # links all three left-col x-axes
    column_widths=[0.52, 0.48],
    vertical_spacing=0.08,
    horizontal_spacing=0.10,
)

# ─── Combined hover text for all left-col bars ────────────────────────────────

hover_combined = [
    f"<b>{r.year}</b><br>"
    f"🌡️  High: {r.max_temp_high:.1f}°C  ·  Low: {r.min_temp_low:.1f}°C<br>"
    f"❄️  Snow: {r.total_snow:.1f} cm<br>"
    f"🌧️  Rain: {r.total_rain:.1f} mm"
    for r in summary.itertuples()
]

# ─── Left col, row 1: temperature range bars ──────────────────────────────────

fig.add_trace(
    go.Bar(
        x=summary["year"],
        y=summary["max_temp_high"] - summary["min_temp_low"],
        base=summary["min_temp_low"],
        marker_color=[temp_color(t) for t in summary["max_temp_high"]],
        marker_line=dict(color="rgba(0,0,0,0.15)", width=0.8),
        hovertext=hover_combined,
        hoverinfo="text",
        showlegend=False,
        name="Temp range",
    ),
    row=1,
    col=1,
)

fig.add_hline(y=0, line_dash="dot", line_color="rgba(180,0,0,0.3)", row=1, col=1)

# ─── Left col, row 2: snow bars ───────────────────────────────────────────────

fig.add_trace(
    go.Bar(
        x=summary["year"],
        y=summary["total_snow"].fillna(0),
        marker_color="#A8D8EA",
        marker_line=dict(color="rgba(0,0,0,0.15)", width=0.8),
        hovertext=hover_combined,
        hoverinfo="text",
        showlegend=False,
        name="Snow",
    ),
    row=2,
    col=1,
)

# ─── Left col, row 3: rain bars ───────────────────────────────────────────────

fig.add_trace(
    go.Bar(
        x=summary["year"],
        y=summary["total_rain"].fillna(0),
        marker_color="#3A9AD9",
        marker_line=dict(color="rgba(0,0,0,0.15)", width=0.8),
        hovertext=hover_combined,
        hoverinfo="text",
        showlegend=False,
        name="Rain",
    ),
    row=3,
    col=1,
)

N_SUMMARY_TRACES = len(fig.data)  # 3 traces
TRACES_PER_YEAR = 3  # temp bar + precip bar + emoji scatter

# ─── Right col: year-detail slider traces ─────────────────────────────────────

for i, year in enumerate(YEARS):
    yr = weather[weather["year"] == year].set_index("day_name")
    visible = i == 0
    x_labels = [DAY_LABELS[d] for d in DAY_ORDER]

    def get(d, col, default=0.0):
        try:
            v = yr.loc[d, col]
            return float(v) if not pd.isna(v) else default
        except KeyError:
            return default

    max_t = [get(d, "max_temp", 10.0) for d in DAY_ORDER]
    min_t = [get(d, "min_temp", 0.0) for d in DAY_ORDER]
    rains = [get(d, "total_rain", 0.0) for d in DAY_ORDER]
    snows = [get(d, "total_snow", 0.0) for d in DAY_ORDER]
    emojis = [yr.loc[d, "emoji"] if d in yr.index else "❓" for d in DAY_ORDER]

    heights = [mx - mn for mx, mn in zip(max_t, min_t)]
    colours = [temp_color(mx) for mx in max_t]
    hover = [
        f"<b>{DAY_LABELS[d]}</b>  {emojis[j]}<br>"
        f"High: {max_t[j]:.1f}°C  Low: {min_t[j]:.1f}°C<br>"
        f"Rain: {rains[j]:.1f} mm    Snow: {snows[j]:.1f} cm"
        for j, d in enumerate(DAY_ORDER)
    ]

    # Trace A: temperature range bars
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=heights,
            base=min_t,
            marker_color=colours,
            marker_line=dict(color="rgba(0,0,0,0.2)", width=1),
            hovertext=hover,
            hoverinfo="text",
            width=0.45,
            visible=visible,
            showlegend=False,
            name=f"Temp {year}",
        ),
        row=1,
        col=2,
    )

    # Trace B: rain + snow bars below zero
    PRECIP_SCALE = 0.8
    rain_ys = [-r * PRECIP_SCALE for r in rains]
    snow_ys = [-s * PRECIP_SCALE for s in snows]
    fig.add_trace(
        go.Bar(
            x=x_labels * 2,
            y=rain_ys + snow_ys,
            base=[0.0] * 3 + rain_ys,
            marker_color=["#3A9AD9"] * 3 + ["#A8D8EA"] * 3,
            marker_line=dict(color="rgba(0,0,0,0.1)", width=0.5),
            hovertext=[f"🌧️ Rain: {rains[j]:.1f} mm" for j in range(3)]
            + [f"❄️ Snow: {snows[j]:.1f} cm" for j in range(3)],
            hoverinfo="text",
            width=0.45,
            visible=visible,
            showlegend=False,
            name=f"Precip {year}",
        ),
        row=1,
        col=2,
    )

    # Trace C: emoji labels above bars
    emoji_y = [mx + max(0.5, (max(max_t) - min(min_t)) * 0.07) for mx in max_t]
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=emoji_y,
            mode="text",
            text=emojis,
            textfont=dict(size=26),
            hoverinfo="skip",
            visible=visible,
            showlegend=False,
            name=f"Emoji {year}",
        ),
        row=1,
        col=2,
    )

# ── Slider ────────────────────────────────────────────────────────────────────

steps = []
for i, year in enumerate(YEARS):
    vis = [True] * N_SUMMARY_TRACES
    for j in range(len(YEARS)):
        vis += [j == i] * TRACES_PER_YEAR
    steps.append(
        dict(
            method="update",
            args=[{"visible": vis}],
            label=str(year),
        )
    )

# ── Final layout ──────────────────────────────────────────────────────────────

fig.update_layout(
    height=560,
    width=None,
    plot_bgcolor="#f8f8f8",
    paper_bgcolor="#ffffff",
    barmode="overlay",
    showlegend=False,
    sliders=[
        dict(
            active=0,
            steps=steps,
            currentvalue=dict(
                prefix="📅  Year: ",
                font=dict(size=13, color="#333"),
                xanchor="center",
            ),
            pad=dict(t=8, b=5),
            x=0.568,
            len=0.432,  # aligned to right (detail) column domain
            y=-0.03,
        )
    ],
    font=dict(family="Arial", size=11),
    margin=dict(t=30, b=70, l=50, r=30),
)

# Y-axes
fig.update_yaxes(
    title_text="°C", row=1, col=1, gridcolor="#e8e8e8", zerolinecolor="#ccc"
)
fig.update_yaxes(title_text="cm", row=2, col=1, gridcolor="#e8e8e8")
fig.update_yaxes(title_text="mm", row=3, col=1, gridcolor="#e8e8e8")
fig.update_yaxes(
    title_text="°C", row=1, col=2, gridcolor="#e8e8e8", zerolinecolor="rgba(0,0,0,0.3)"
)

# X-axes: only show tick labels on bottom row of left column
fig.update_xaxes(showticklabels=False, row=1, col=1)
fig.update_xaxes(showticklabels=False, row=2, col=1)
fig.update_xaxes(tickmode="linear", dtick=2, row=3, col=1)

# Detail: zero line, year label (annotations[3]), and rain/snow legend (annotations[4])
fig.add_hline(y=0, line_dash="dash", line_color="rgba(0,0,0,0.3)", row=1, col=2)
fig.add_annotation(
    x=0.76,
    y=1.05,
    xref="paper",
    yref="paper",
    text=f"<b>{YEARS[0]}  —  Victoria Day Weekend</b>",
    showarrow=False,
    xanchor="center",
)
fig.add_annotation(
    x=0.99,
    y=0.01,
    xref="paper",
    yref="paper",
    text="<span style='color:#3A9AD9'>■</span> Rain (mm)  <span style='color:#A8D8EA'>■</span> Snow (cm)",
    showarrow=False,
    align="right",
    font=dict(size=10),
    bgcolor="rgba(255,255,255,0.85)",
    bordercolor="rgba(0,0,0,0.1)",
    borderwidth=1,
)

out_path = "may_long_dashboard.html"

# Clicking any point on the top 3 charts jumps the detail slider to that year.
click_js = (
    """
(function() {
    var gd = document.getElementById('{plot_id}');
    var YEARS = """
    + str(YEARS)
    + """;
    var N_SUMMARY = """
    + str(N_SUMMARY_TRACES)
    + """;
    var TPY = """
    + str(TRACES_PER_YEAR)
    + """;

    function updateYearLabel(year) {
        var annos = gd.layout.annotations.map(function(a) {
            return Object.assign({}, a);
        });
        annos[3].text = '<b>' + year + '  —  Victoria Day Weekend</b>';
        Plotly.relayout(gd, {annotations: annos});
    }

    function highlightYear(year) {
        var idx = YEARS.indexOf(year);
        if (idx === -1) return;
        var colors = YEARS.map(function(_, i) {
            return i === idx ? '#000000' : 'rgba(0,0,0,0.15)';
        });
        var widths = YEARS.map(function(_, i) {
            return i === idx ? 2 : 0.8;
        });
        Plotly.restyle(gd,
            {'marker.line.color': [colors, colors, colors],
             'marker.line.width': [widths, widths, widths]},
            [0, 1, 2]
        );
    }

    // Initialise on load
    highlightYear(YEARS[0]);

    // Slider moved interactively
    gd.on('plotly_sliderchange', function(data) {
        var year = parseInt(data.step.label);
        highlightYear(year);
        updateYearLabel(year);
    });

    // Pointer cursor when hovering over summary traces
    gd.on('plotly_hover', function(data) {
        if (data.points[0].fullData.index < N_SUMMARY) gd.style.cursor = 'pointer';
    });
    gd.on('plotly_unhover', function() { gd.style.cursor = 'default'; });

    gd.on('plotly_click', function(data) {
        if (!data.points || !data.points.length) return;
        var pt = data.points[0];
        if (pt.fullData.index >= N_SUMMARY) return;
        var year = pt.x;
        if (typeof year !== 'number') return;
        var stepIdx = YEARS.indexOf(year);
        if (stepIdx === -1) return;

        var vis = [];
        for (var i = 0; i < N_SUMMARY; i++) vis.push(true);
        for (var j = 0; j < YEARS.length; j++) {
            var on = (j === stepIdx);
            for (var t = 0; t < TPY; t++) vis.push(on);
        }

        var stepArgs = gd._fullLayout.sliders[0].steps[stepIdx].args;
        Plotly.update(gd, {visible: vis}, stepArgs[1]);
        Plotly.relayout(gd, {'sliders[0].active': stepIdx});
        highlightYear(year);
        updateYearLabel(year);
    });
})();
"""
)

fig.write_html(out_path, include_plotlyjs="cdn", post_script=click_js)

# ── Stat cards ────────────────────────────────────────────────────────────────

n_years = len(YEARS)
pct_rain = round(
    100 * weather.groupby("year")["total_rain"].sum().gt(0.1).sum() / n_years
)
pct_below = round(100 * weather.groupby("year")["min_temp"].min().lt(0).sum() / n_years)
pct_snow = round(
    100 * weather.groupby("year")["total_snow"].sum().gt(0.1).sum() / n_years
)
pct_above = round(
    100 * weather.groupby("year")["max_temp"].max().gt(20).sum() / n_years
)

# Nicest/nastiest: score = weekend_high + weekend_low − rain − snow×3
yr_scores = summary.copy()
yr_scores["score"] = (
    yr_scores["max_temp_high"]
    + yr_scores["min_temp_low"]
    - yr_scores["total_rain"]
    - yr_scores["total_snow"] * 3
)


def yr_summary_str(year):
    row = summary[summary["year"] == year].iloc[0]
    return (
        f"{row.max_temp_high:.0f}°C high · {row.min_temp_low:.0f}°C low<br>"
        f"Rain {row.total_rain:.0f} mm · Snow {row.total_snow:.0f} cm"
    )


nicest_year = int(yr_scores.loc[yr_scores["score"].idxmax(), "year"])
nastiest_year = int(yr_scores.loc[yr_scores["score"].idxmin(), "year"])

cards = [
    ("🌧️", f"{pct_rain}%", "of years had rain", "#3A9AD9", "#EBF5FB", None),
    ("🥶", f"{pct_below}%", "of years dipped below 0°C", "#5B8DB8", "#EAF2FF", None),
    ("❄️", f"{pct_snow}%", "of years had snow", "#7EC8E3", "#F0F9FF", None),
    ("☀️", f"{pct_above}%", "of years hit above 20°C", "#E87C2A", "#FEF6EC", None),
    (
        "🏆",
        str(nicest_year),
        f"nicest weekend<br><span style='font-size:11px;color:#888'>{yr_summary_str(nicest_year)}</span>",
        "#F4A800",
        "#FFFBEE",
        "nicest",
    ),
    (
        "😰",
        str(nastiest_year),
        f"nastiest weekend<br><span style='font-size:11px;color:#888'>{yr_summary_str(nastiest_year)}</span>",
        "#7B4F9E",
        "#F9F0FF",
        "nastiest",
    ),
]

card_html = """
<div style="text-align:center; font-family:Arial,sans-serif; padding: 16px 0 0;">
    <div style="font-size:22px; font-weight:bold; color:#222;">Calgary May Long Weekend Weather</div>
    <div style="font-size:12px; color:#888; margin-top:3px;">Victoria Day weekend &nbsp;·&nbsp; Calgary International Airport &nbsp;·&nbsp; Past 20 Years</div>
</div>
<div style="
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 12px;
    padding: 14px 30px 6px;
    font-family: Arial, sans-serif;
">
"""
for emoji, value, label, colour, bg, kind in cards:
    extra_width = "min-width: 170px;" if kind else "min-width: 130px;"
    card_html += f"""
    <div style="
        background: {bg};
        border-radius: 12px;
        padding: 12px 18px;
        text-align: center;
        {extra_width}
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-top: 3px solid {colour};
    ">
        <div style="font-size: 22px; margin-bottom: 2px;">{emoji}</div>
        <div style="font-size: 26px; font-weight: bold; color: {colour}; line-height: 1.15;">{value}</div>
        <div style="color: #555; font-size: 11px; margin-top: 4px;">{label}</div>
    </div>"""
card_html += "\n</div>\n"

# Inject the cards just before the plotly <div>
html = open(out_path).read()
html = html.replace("<div id=", card_html + "<div id=", 1)
open(out_path, "w").write(html)

print(f"Dashboard saved → {out_path}")

import subprocess, sys

if sys.platform == "darwin":
    subprocess.run(["open", out_path], check=False)
