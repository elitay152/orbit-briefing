"""Build the static dashboard: run the analyses, write their charts, and render one HTML page.

    python -m orbit.site.build --out site

Point LAKE_DIR at a copy of the data branch's orbital_elements folder to build from the daily
history; by default this reads the local lake. Every number on the page is computed here.
"""
import argparse
from datetime import datetime, timezone
import html
import json
import logging
import math
from pathlib import Path
import shutil

import duckdb
import pandas as pd
from skyfield.api import load

from orbit.analysis.prediction_error import (
    DAY_OLD, MANEUVER_ALT_KM, day_old_medians, format_date_range, load_frames, plot_errors,
)
from orbit.analysis.satellite_map import map_points, plot_map
from orbit.analysis.theme import DARK
from orbit.analysis.spc import ALTITUDE_CHANGE_KM, MIN_BASELINE_POINTS, laney_limits, rate_signals, run_spc
from orbit.config import setup_logging, ANALYSIS_DIR, DISPLAY_NAMES
from orbit.site.diagram import draw_diagram

logger = logging.getLogger(__name__)

# constants
REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "demo"
EVAL_SUMMARY = DEMO_DIR / "eval_summary.json"
AGENT_SCREENSHOTS = ["agent_ui_answer.jpg", "agent_ui_guardrail.jpg"]
REPO_URL = "https://github.com/elitay152/orbit-briefing"
SITE_URL = "https://elitay152.github.io/orbit-briefing/"   # link previews need absolute URLs
PREVIEW_SIZE = (1800, 1050)                                 # the map image: 12 × 7 in at 150 dpi
DISCLAIMER = ("Independent personal project using public data; "
              "not affiliated with Amazon, SpaceX or CelesTrak.")

# images written this build; cards whose images are missing are left out
AVAILABLE: set[str] = set()

IMAGES = {
    "map": "satellite_map.png",
    "prediction_error": "prediction_error.png",
    "spc_altitude": "spc_altitude_change.png",
    "spc_freshness": "spc_data_age.png",
    "diagram": "pipeline_diagram.png",
}

def name(group: str) -> str:
    return DISPLAY_NAMES.get(group, group)

def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))

def compute_kpis(points: pd.DataFrame, frames: dict[str, pd.DataFrame],
                 metrics: pd.DataFrame, positions_at: datetime) -> dict:
    """Headline numbers for the tiles. Values that can't be computed are None."""
    counts = points.groupby("constellation").size().to_dict()
    changed_share = points.groupby("constellation")["changed"].mean().to_dict()

    held = changed = None
    if frames:
        held, changed = day_old_medians(frames)
    ratio = None if is_missing(held) or is_missing(changed) or held == 0 else changed / held

    times = pd.to_datetime(metrics["snapshot_time"]) if not metrics.empty else pd.Series(dtype="datetime64[ns]")
    snapshots = int(metrics.groupby("constellation")["snapshot_time"].nunique().max()) if not metrics.empty else 0

    return {
        "satellites": len(points),
        "counts": counts,
        "changed": int(points["changed"].sum()),
        "changed_share": changed_share,
        "held_km": None if is_missing(held) else float(held),
        "changed_km": None if is_missing(changed) else float(changed),
        "ratio": ratio,
        "snapshots": snapshots,
        "date_range": format_date_range(times.min(), times.max()) if snapshots else "",
        "positions_at": positions_at,
    }

def load_evaluation(summary_path: Path = EVAL_SUMMARY, analysis_dir: Path = ANALYSIS_DIR) -> dict | None:
    """The hand-reviewed evaluation summary, plus the newest local held-out run if there is one."""
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    runs = sorted(analysis_dir.glob("eval_heldout_*.csv"))
    if runs:
        latest = pd.read_csv(runs[-1])
        summary["latest_run"] = {"correct": int(latest["correct"].sum()), "questions": len(latest),
                                 "file": runs[-1].name}
    return summary

def p_chart_summary(changes: pd.DataFrame) -> dict:
    """Mean share changed and number of signals per constellation."""
    summary = {}
    for group, df in changes.groupby("constellation"):
        if len(df) < 2:
            continue
        limits = laney_limits(df["changed"].tolist(), df["compared"].tolist())
        summary[group] = {"p_bar": limits["p_bar"], "signals": sum(rate_signals(limits)), "points": len(df)}
    return summary

def fmt(value, spec: str = ",.0f", missing: str = "—") -> str:
    return missing if is_missing(value) else format(value, spec)

def when_text(moment: datetime) -> str:
    return f"{moment:%b} {moment.day}, {moment:%Y} {moment:%H:%M} UTC"

def tile(label: str, value: str, detail: str) -> str:
    return (f'<div class="tile"><div class="tile-label">{html.escape(label)}</div>'
            f'<div class="tile-value">{html.escape(value)}</div>'
            f'<div class="tile-detail">{html.escape(detail)}</div></div>')

def card(title: str, caption: str, images: list[tuple[str, str]], dark: bool = False) -> str:
    """A chart card; returns "" if any of its images wasn't produced."""
    if any(src not in AVAILABLE for src, _ in images):
        return ""
    figures = "".join(f'<img src="images/{html.escape(src)}" alt="{html.escape(alt)}" loading="lazy">'
                      for src, alt in images)
    return (f'<section class="card{" dark" if dark else ""}"><h2>{html.escape(title)}</h2>'
            f'<p class="caption">{html.escape(caption)}</p><div class="figures">{figures}</div></section>')

def prediction_title(ratio: float | None) -> str:
    """Card title for the prediction-error chart, worded to fit whatever the ratio turns out to be."""
    if ratio is None:
        return "How fast satellite orbit predictions go stale"
    if ratio >= 1.5:
        return f"Satellites that change altitude are about {ratio:.0f}× harder to predict"
    if ratio > 1 / 1.5:
        return "Satellites that change altitude are about as predictable as those that don't"
    return "Satellites that change altitude are, surprisingly, easier to predict"

def rate_comparison_title(spc: dict) -> str:
    """Card title comparing how often each constellation changes altitude, whichever is higher."""
    if len(spc) != 2:
        return "How many satellites change altitude each day"
    (low, low_stats), (high, high_stats) = sorted(spc.items(), key=lambda item: item[1]["p_bar"])
    if low_stats["p_bar"] == 0:
        return f"{name(high)} satellites change altitude; {name(low)}'s almost never do"
    ratio = high_stats["p_bar"] / low_stats["p_bar"]
    if ratio < 1.5:
        return f"{name(low)} and {name(high)} satellites change altitude at similar rates"
    return f"{name(high)} satellites change altitude about {ratio:.0f}× as often as {name(low)}'s"

def signals_text(signals: int) -> str:
    """'No unusual days so far.', '1 unusual day flagged…', or 'N unusual days flagged…'."""
    if signals == 0:
        return "No unusual days so far."
    if signals == 1:
        return "1 unusual day flagged; it's marked on the chart."
    return f"{signals} unusual days flagged; they're marked on the chart."

def limits_note(points: int, unit: str) -> str:
    """Caveat on the control limits, which only stops saying 'preliminary' once there's enough history."""
    if points < MIN_BASELINE_POINTS:
        return (f"Preliminary: {points:,} {unit} so far, and limits are usually set from about "
                f"{MIN_BASELINE_POINTS} points.")
    return f"Limits are calculated from all {points:,} {unit}."

def preview_tags(kpis: dict) -> str:
    """Open Graph and Twitter tags, so a shared link shows a card with the satellite map."""
    description = (f"A daily data pipeline tracking {kpis['satellites']:,} Amazon Leo and Starlink "
                   "satellites from public orbit data: GitHub Actions, Parquet, DuckDB, and a live map.")
    image = SITE_URL + "images/" + IMAGES["map"]
    alt = "World map of every tracked Amazon Leo and Starlink satellite"
    tags = [
        ("property", "og:type", "website"),
        ("property", "og:site_name", "Orbit Briefing"),
        ("property", "og:title", "Orbit Briefing: tracking every Amazon Leo and Starlink satellite"),
        ("property", "og:description", description),
        ("property", "og:url", SITE_URL),
        ("property", "og:image", image),
        ("property", "og:image:width", str(PREVIEW_SIZE[0])),
        ("property", "og:image:height", str(PREVIEW_SIZE[1])),
        ("property", "og:image:alt", alt),
        ("name", "twitter:card", "summary_large_image"),
        ("name", "twitter:image", image),
        ("name", "description", description),
    ]
    return "\n".join(f'<meta {attr}="{key}" content="{html.escape(value)}">' for attr, key, value in tags)

def render_page(kpis: dict, frames: dict[str, pd.DataFrame], spc: dict, metrics: pd.DataFrame,
                evaluation: dict | None, built_at: datetime) -> str:
    """The whole dashboard as one self-contained HTML page."""
    counts = kpis["counts"]
    count_detail = " · ".join(f"{name(g)} {n:,}" for g, n in sorted(counts.items()))
    share_detail = " · ".join(f"{name(g)} {s:.1%}" for g, s in sorted(kpis["changed_share"].items()))

    tiles = [
        tile("Satellites tracked", f"{kpis['satellites']:,}", count_detail),
        tile("Changed altitude since the previous snapshot", f"{kpis['changed']:,}", share_detail),
        tile("Prediction error: changed vs. held altitude",
             f"≈{fmt(kpis['ratio'], '.0f')}×" if kpis["ratio"] else "—",
             f"Median error on day-old data: {fmt(kpis['held_km'])} km held vs. "
             f"{fmt(kpis['changed_km'])} km changed"),
        tile("Snapshots", f"{kpis['snapshots']:,}", kpis["date_range"]),
        tile("Last data update", when_text(kpis["positions_at"]), f"Page built {when_text(built_at)}"),
    ]

    pairs = sum(len(df) for df in frames.values())
    signals = sum(s["signals"] for s in spc.values())
    comparisons = min((s["points"] for s in spc.values()), default=0)

    ages = metrics["median_age_hours"] if not metrics.empty else pd.Series(dtype=float)
    freshness_title = (f"Orbit data is typically about {ages.median():.0f} hours old when the pipeline fetches it"
                       if len(ages) else "How old the orbit data is when it's fetched")

    cards = [
        card(f"Every satellite I'm tracking: {kpis['satellites']:,}, with {kpis['changed']:,} changing altitude",
             f"Positions computed with SGP4 at {when_text(kpis['positions_at'])}. Ringed satellites changed "
             f"altitude by more than {ALTITUDE_CHANGE_KM} km since the previous snapshot. That can be a "
             "maneuver, atmospheric drag, or noise in the orbit data, so it doesn't necessarily mean the "
             "satellite maneuvered.",
             [(IMAGES["map"], f"World map of {kpis['satellites']:,} Amazon Leo and Starlink satellites, "
                              f"with {kpis['changed']:,} that changed altitude ringed")], dark=True),
        card(prediction_title(kpis["ratio"]),
             f"Each orbit record is propagated to the next one with SGP4 and compared with it: "
             f"{pairs:,} prediction pairs. The right panel uses data {DAY_OLD[0]}–{DAY_OLD[1]} days old; "
             f"'changed' means more than {MANEUVER_ALT_KM} km. Small altitude changes shift a satellite's "
             "timing, which builds up as along-track error.",
             [(IMAGES["prediction_error"], "Two charts: median prediction error rising as orbit data ages "
                                           "for each constellation, and much larger errors for satellites "
                                           "whose altitude changed")]),
        card(rate_comparison_title(spc),
             f"A Laney p′ control chart of the share of satellites changing altitude by more than "
             f"{ALTITUDE_CHANGE_KM} km between daily snapshots. {signals_text(signals)} "
             f"{limits_note(comparisons, 'daily comparisons')}",
             [(IMAGES["spc_altitude"], "Control charts of the daily share of Amazon Leo and Starlink "
                                       "satellites changing altitude, with control limits")]),
        card(freshness_title,
             "An individuals control chart of the median age of the orbit data at each fetch, as a "
             f"pipeline-health check. {limits_note(kpis['snapshots'], 'snapshots')} "
             "The time of day the job runs also affects the age.",
             [(IMAGES["spc_freshness"], "Control charts of the median age of the orbit data at each "
                                        "snapshot, for Amazon Leo and Starlink")]),
        evaluation_card(evaluation),
        card("How the pipeline works",
             "GitHub Actions fetches public CelesTrak data daily, validates it into a partitioned Parquet "
             "lake, and DuckDB queries that lake for every chart on this page. The page rebuilds after "
             "each daily snapshot.",
             [(IMAGES["diagram"], "Pipeline diagram: CelesTrak to extract, validate and a Parquet lake, "
                                  "queried with DuckDB for the briefing, prediction error, control "
                                  "charts and AI analyst")], dark=True),
    ]

    return PAGE.format(
        preview=preview_tags(kpis),
        tiles="".join(tiles), cards="".join(cards), repo=REPO_URL,
        updated=html.escape(when_text(kpis["positions_at"])), disclaimer=html.escape(DISCLAIMER),
    )

def evaluation_card(evaluation: dict | None) -> str:
    """The AI analyst card: evaluated locally, since the model needs Ollama."""
    screenshots = [(AGENT_SCREENSHOTS[0], "The AI analyst answering which Amazon Leo launch has the most "
                                          "satellites, with its SQL shown"),
                   (AGENT_SCREENSHOTS[1], "The AI analyst refusing to delete data: the model's DELETE "
                                          "query is rejected by the guardrail")]
    if evaluation is None:
        return card("A local AI analyst that writes read-only SQL",
                    "It runs on a local model, so it isn't part of this page's automatic rebuild.",
                    screenshots)

    held = evaluation["heldout"]
    tuning = evaluation["tuning"]
    reviewed = held["reviewed_correct"] / held["questions"]
    caption = (f"Ask a question in plain English; a local model ({evaluation['model']}) writes read-only "
               f"SQL against a locked-down DuckDB sandbox. On {held['questions']} questions it wasn't tuned "
               f"on, it got {held['reviewed_correct']} right after reading the answers. The automatic score "
               f"said {held['automatic_correct']}: {held['note']} "
               f"Fixes took the tuning set from {tuning['baseline_correct']} to "
               f"{tuning['after_fixes_correct']} of {tuning['questions']}. Evaluated locally, because the "
               "model runs on Ollama rather than in CI; small question sets, so treat these as rough.")
    if "latest_run" in evaluation:
        run = evaluation["latest_run"]
        caption += f" Latest local automatic run: {run['correct']} of {run['questions']}."
    return card(f"A local AI analyst that writes SQL: {reviewed:.0%} on questions it wasn't tuned on",
                caption, screenshots)

def build_site(out_dir: Path) -> Path:
    """Run every analysis, write the charts into out_dir/images, and write out_dir/index.html."""
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    ts = load.timescale()

    with duckdb.connect() as con:
        points, positions_at = map_points(con, ts)
    plot_map(points, positions_at, images_dir / IMAGES["map"])

    frames = load_frames(ts)
    if frames:
        plot_errors(frames, images_dir / IMAGES["prediction_error"], DARK)

    metrics, changes = run_spc(images_dir / IMAGES["spc_altitude"], images_dir / IMAGES["spc_freshness"], DARK)
    draw_diagram(images_dir / IMAGES["diagram"])
    for screenshot in AGENT_SCREENSHOTS:
        shutil.copy(DEMO_DIR / screenshot, images_dir / screenshot)
    AVAILABLE.clear()
    AVAILABLE.update(path.name for path in images_dir.iterdir())

    kpis = compute_kpis(points, frames, metrics, positions_at)
    page = render_page(kpis, frames, p_chart_summary(changes), metrics, load_evaluation(),
                       datetime.now(timezone.utc))
    index = out_dir / "index.html"
    index.write_text(page, encoding="utf-8")
    return index

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orbit Briefing</title>
<link rel="canonical" href="https://elitay152.github.io/orbit-briefing/">
{preview}
<style>
  :root {{
    color-scheme: dark;
    --page: #0b1019; --surface: rgba(20, 27, 39, 0.88); --ink: #f0efec; --ink-2: #c3c2b7;
    --muted: #8d93a0; --line: #263044; --accent: #6da7ec; --dark: #0e1420;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; color: var(--ink); min-height: 100vh;
          background: radial-gradient(ellipse at 20% 0%, #16213a 0%, var(--page) 55%) fixed, var(--page);
          font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}

  /* starfield: two tiled layers of tiny dots that twinkle out of step */
  body::before, body::after {{
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  }}
  body::before {{
    background-image:
      radial-gradient(1px 1px at 23px 41px, #fff, transparent),
      radial-gradient(1px 1px at 141px 87px, #cdd6ff, transparent),
      radial-gradient(1.5px 1.5px at 210px 160px, #fff, transparent),
      radial-gradient(1px 1px at 77px 199px, #fff, transparent),
      radial-gradient(1px 1px at 269px 23px, #ffe9c4, transparent),
      radial-gradient(1px 1px at 180px 255px, #fff, transparent);
    background-size: 300px 300px;
    animation: twinkle 5s ease-in-out infinite alternate;
  }}
  body::after {{
    background-image:
      radial-gradient(1px 1px at 61px 131px, #fff, transparent),
      radial-gradient(1.5px 1.5px at 333px 59px, #cdd6ff, transparent),
      radial-gradient(1px 1px at 241px 307px, #fff, transparent),
      radial-gradient(1px 1px at 397px 211px, #fff, transparent),
      radial-gradient(2px 2px at 121px 371px, #ffffff, transparent),
      radial-gradient(1px 1px at 19px 289px, #ffe9c4, transparent);
    background-size: 430px 430px;
    animation: twinkle 7s ease-in-out infinite alternate-reverse;
  }}
  @keyframes twinkle {{ from {{ opacity: 0.25; }} to {{ opacity: 0.85; }} }}
  @media (prefers-reduced-motion: reduce) {{
    body::before, body::after {{ animation: none; opacity: 0.6; }}
  }}

  main {{ position: relative; z-index: 1; max-width: 1120px; margin: 0 auto; padding: 32px 16px 48px; }}
  header {{ margin-bottom: 24px; }}
  h1 {{ font-size: 2rem; margin: 0 0 4px; }}
  .lede {{ color: var(--ink-2); margin: 0 0 12px; max-width: 60ch; }}
  .meta {{ display: flex; flex-wrap: wrap; gap: 8px 20px; color: var(--muted); font-size: 0.9rem; }}
  .meta a {{ color: var(--accent); }}
  .disclaimer {{ color: var(--muted); font-size: 0.85rem; margin-top: 8px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .tile {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }}
  .tile-label {{ color: var(--ink-2); font-size: 0.85rem; }}
  .tile-value {{ font-size: 1.6rem; font-weight: 700; margin: 4px 0; }}
  .tile-detail {{ color: var(--muted); font-size: 0.8rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
           padding: 20px; margin-bottom: 20px; }}
  .card h2 {{ font-size: 1.25rem; margin: 0 0 6px; }}
  .caption {{ color: var(--ink-2); font-size: 0.95rem; margin: 0 0 14px; max-width: 80ch; }}
  .figures {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
  .tile, .card {{ backdrop-filter: blur(2px); }}
  .figures img {{ width: 100%; height: auto; display: block; border-radius: 8px; border: 1px solid var(--line); }}
  .card.dark .figures img {{ background: var(--dark); }}
  a {{ color: var(--accent); }}
  footer {{ color: var(--muted); font-size: 0.85rem; text-align: center; margin-top: 32px; }}
  @media (max-width: 600px) {{
    h1 {{ font-size: 1.6rem; }}
    .figures {{ grid-template-columns: 1fr; }}
    .card {{ padding: 16px; }}
  }}
</style>
</head>
<body>
<main>
<header>
  <h1>Orbit Briefing</h1>
  <p class="lede">A daily data pipeline tracking Amazon Leo and Starlink satellites from public orbit data:
  where they are, how quickly predictions go stale, and whether anything unusual is happening.</p>
  <div class="meta"><span>Data updated {updated}</span><a href="{repo}">Code on GitHub</a></div>
  <p class="disclaimer">{disclaimer}</p>
</header>
<div class="tiles">{tiles}</div>
{cards}
<footer>{disclaimer} · <a href="{repo}">{repo}</a></footer>
</main>
</body>
</html>
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the static dashboard.")
    parser.add_argument("--out", type=Path, default=Path("site"), help="output folder")
    args = parser.parse_args()

    setup_logging()
    index = build_site(args.out)
    logger.info("Dashboard written to %s", index)
