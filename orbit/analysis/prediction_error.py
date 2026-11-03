import duckdb
import logging
import math
from pathlib import Path
from itertools import groupby, pairwise
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from skyfield.api import load, EarthSatellite, Timescale

from orbit.analysis.theme import LIGHT, style_axes
from orbit.pipeline.transform import to_omm
from orbit.config import setup_logging, LAKE_GLOB, GROUP_LIST, ANALYSIS_DIR, DISPLAY_NAMES

# constants
EARTH_MU = 398600.4418       # Earth's gravitational constant, km³/s²
EARTH_RADIUS_KM = 6378.137
MANEUVER_ALT_KM = 0.5   # altitude change (km) needed to call a flagged pair raising/lowering

# chart settings
AGE_BINS = np.arange(0, 2.01, 0.25)    # days; left panel
ALT_BINS = [0, 0.5, 2, 10, np.inf]    # km of altitude change; right panel
ALT_LABELS = ["Under 0.5 km\n(held altitude)", "0.5–2 km", "2–10 km", "Over 10 km"]
DAY_OLD = (0.5, 1.5)                  # "about a day old" window for the right panel

ALL_ELEMENTS_SQL = f"""
    SELECT * FROM read_parquet('{LAKE_GLOB}', hive_partitioning = true)
    WHERE constellation = ?
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY norad_cat_id, epoch
        ORDER BY source_file DESC
    ) = 1
    ORDER BY norad_cat_id, epoch
"""

logger = logging.getLogger(__name__)

def altitude_km(mean_motion: float) -> float:
    """Approximate altitude (km) from mean motion in orbits per day."""
    n = mean_motion * 2 * math.pi / 86400      # orbits/day → radians/second
    a = (EARTH_MU / n**2) ** (1/3)             # orbit radius in km
    return a - EARTH_RADIUS_KM

def all_elements(con: duckdb.DuckDBPyConnection,
                    constellation: str) -> list[dict]:
    """Return the unique orbital elements for a given group from the Parquet lake."""

    cursor = con.execute(ALL_ELEMENTS_SQL, [constellation])
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

def prediction_errors(records: list[dict],
                      ts: Timescale,
                      constellation: str) -> list[dict]:
    """For each consecutive pair of a satellite’s records,
    propagate the older one to the newer epoch; return position error and altitude change."""

    errors = []

    # split into one group per satellite
    for norad_id, sat_records in groupby(records, key=lambda r: r["norad_cat_id"]):
        for older, newer in pairwise(sat_records):
            sat_older = EarthSatellite.from_omm(ts, to_omm(older))
            sat_newer = EarthSatellite.from_omm(ts, to_omm(newer))

            t = ts.from_datetime(newer["epoch"])
            old_pos = sat_older.at(t).position.km
            new_pos = sat_newer.at(t).position.km

            # calculate error
            error = float(np.linalg.norm(old_pos - new_pos))
            age_days = (newer["epoch"] - older["epoch"]).total_seconds() / 86400
            altitude_change = altitude_km(newer["mean_motion"]) - altitude_km(older["mean_motion"])

            errors.append({
                "norad_cat_id": norad_id,
                "constellation": constellation,
                "object_name": newer["object_name"],
                "object_id": newer["object_id"],
                "epoch": newer["epoch"],
                "age_days": age_days,
                "error_km": error,
                "altitude_change_km": altitude_change,
            })

    return errors

def classify(row) -> str:
    """Label a pair 'normal', 'raising', 'lowering',
    or 'small/unclear' from its flag and altitude change."""

    if not row["flagged"]:
        return "normal"
    if row["altitude_change_km"] > MANEUVER_ALT_KM:
        return "raising"
    if row["altitude_change_km"] < -MANEUVER_ALT_KM:
        return "lowering"
    return "small/unclear"

def format_date_range(start, end) -> str:
    """'Oct 28 – Nov 3, 2026', or 'Dec 30, 2026 – Jan 2, 2027' when the years differ."""
    start_fmt = f"{start:%b} {start.day}" + ("" if start.year == end.year else f", {start.year}")
    return f"{start_fmt} – {end:%b} {end.day}, {end.year}"

def date_range_text(frames: dict[str, pd.DataFrame]) -> str:
    """Date range of the frames' epoch column (empty if there isn't one)."""
    epochs = [pd.to_datetime(df["epoch"], utc=True) for df in frames.values() if "epoch" in df]
    if not epochs:
        return ""
    return format_date_range(min(e.min() for e in epochs), max(e.max() for e in epochs))

def plot_errors(frames: dict[str, pd.DataFrame], path: Path, theme: dict = LIGHT) -> Path:
    """Two panels: median error vs. age per constellation (middle 50% shaded),
    and median error by altitude change for orbit data about a day old."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6.3),
                                   gridspec_kw={"width_ratios": [1.25, 1]})
    fig.patch.set_facecolor(theme["surface"])

    # left: how error grows as the orbit data ages
    centers = (AGE_BINS[:-1] + AGE_BINS[1:]) / 2
    for group, df in frames.items():
        binned = pd.cut(df["age_days"], AGE_BINS)
        stats = df.groupby(binned, observed=False)["error_km"].quantile([0.25, 0.5, 0.75]).unstack()
        color = theme["series"].get(group, theme["muted"])
        name = DISPLAY_NAMES.get(group, group)

        ax1.fill_between(centers, stats[0.25], stats[0.75], color=color, alpha=theme["band_alpha"], linewidth=0)
        ax1.plot(centers, stats[0.5], color=color, linewidth=2.2, marker="o", markersize=5,
                 markeredgecolor=theme["surface"], markeredgewidth=1.5, label=name)

        # label the end of each line directly
        last = stats[0.5].dropna()
        ax1.annotate(f"{name}\n{last.iloc[-1]:.0f} km", xy=(centers[len(last) - 1], last.iloc[-1]),
                     xytext=(8, 0), textcoords="offset points", va="center",
                     fontsize=10, color=theme["ink_2"])

    style_axes(ax1, theme)
    ax1.set_xlim(0, AGE_BINS[-1] + 0.35)
    ax1.set_ylim(bottom=0)
    ax1.set_xlabel("Age of orbit data (days)", color=theme["ink_2"])
    ax1.set_ylabel("Median position error (km)", color=theme["ink_2"])
    ax1.set_title("Predictions drift as orbit data ages", loc="left", fontsize=12, color=theme["ink"], pad=10)
    ax1.legend(loc="upper left", frameon=False, fontsize=10, labelcolor=theme["ink_2"])
    fig.text(0.06, 0.035, "Shaded: middle 50% of satellites", fontsize=9, color=theme["muted"])

    # right: error by altitude change, for orbit data about a day old
    both = pd.concat(frames.values())
    day_old = both[(both["age_days"] >= DAY_OLD[0]) & (both["age_days"] < DAY_OLD[1])]
    change = pd.cut(day_old["altitude_change_km"].abs(), ALT_BINS, include_lowest=True)
    medians = day_old.groupby(change, observed=False)["error_km"].median().to_numpy()

    x = np.arange(len(ALT_LABELS))
    ax2.bar(x, medians, width=0.6, color=theme["bar"], edgecolor=theme["surface"], linewidth=2)
    for xi, m in zip(x, medians):
        ax2.annotate(f"{m:,.0f} km", xy=(xi, m), xytext=(0, 4), textcoords="offset points",
                     ha="center", va="bottom", fontsize=10, color=theme["ink"])

    style_axes(ax2, theme)
    ax2.set_xticks(x, ALT_LABELS)
    ax2.set_ylim(0, np.nanmax(medians) * 1.18)
    ax2.set_xlabel("How much the satellite's altitude changed", color=theme["ink_2"])
    ax2.set_ylabel("Median position error (km)", color=theme["ink_2"])
    ax2.set_title("…and a small altitude change throws them far off",
                  loc="left", fontsize=12, color=theme["ink"], pad=10)
    fig.text(0.585, 0.035,
             f"Right: orbit data about 1 day old. Worst case: {day_old['error_km'].max():,.0f} km off.",
             fontsize=9, color=theme["muted"])

    # title and subtitle (date range comes from the data)
    fig.suptitle("How fast do satellite orbit predictions go stale?",
                 x=0.012, y=0.975, ha="left", fontsize=15, color=theme["ink"], fontweight="bold")
    subtitle = "Each orbit record propagated to the next one with SGP4 · Public CelesTrak data"
    dates = date_range_text(frames)
    fig.text(0.012, 0.912, f"{subtitle}, {dates}" if dates else subtitle,
             ha="left", fontsize=10, color=theme["ink_2"])

    fig.subplots_adjust(left=0.06, right=0.98, top=0.82, bottom=0.2, wspace=0.22)
    fig.savefig(path, dpi=150, facecolor=theme["surface"])
    plt.close(fig)
    return path

def compute_frames(records_by_group: dict[str, list[dict]], ts: Timescale) -> dict[str, pd.DataFrame]:
    """Prediction errors per constellation, flagged and classified. Groups with no pairs are skipped."""
    frames = {}
    for group, records in records_by_group.items():
        errors = prediction_errors(records, ts, group)
        logger.info("%s: %d records, %d pairs", group, len(records), len(errors))
        if not errors:
            continue

        df = pd.DataFrame(errors)
        df["age_bucket"] = df["age_days"].round()

        # flag first, then classify (classify reads "flagged")
        bucket_median = df.groupby("age_bucket")["error_km"].transform("median")
        df["flagged"] = df["error_km"] > 10 * bucket_median
        df["event"] = df.apply(classify, axis=1)
        frames[group] = df

    return frames

def load_frames(ts: Timescale) -> dict[str, pd.DataFrame]:
    """Query the lake, close the connection, then compute the frames."""
    with duckdb.connect() as con:
        records_by_group = {group: all_elements(con, group) for group in GROUP_LIST}
    return compute_frames(records_by_group, ts)

def day_old_medians(frames: dict[str, pd.DataFrame]) -> tuple[float, float]:
    """Median error of about-a-day-old data: (held altitude, changed altitude). NaN if a group is empty."""
    both = pd.concat(frames.values())
    day_old = both[(both["age_days"] >= DAY_OLD[0]) & (both["age_days"] < DAY_OLD[1])]
    changed = day_old["altitude_change_km"].abs() > MANEUVER_ALT_KM
    return day_old.loc[~changed, "error_km"].median(), day_old.loc[changed, "error_km"].median()

if __name__ == "__main__":

    setup_logging()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["norad_cat_id", "object_name", "age_days", "error_km", "altitude_change_km", "event"]

    frames = load_frames(load.timescale())

    for group, df in frames.items():
        print(f"\n=== {group} ===")
        summary = df.groupby("age_bucket")["error_km"].agg(["count", "median", "mean", "max"])
        print(summary.round(1).to_string())

        print("\nLargest errors:")
        print(df.nlargest(10, "error_km")[cols].to_string(index=False))

        print(f"\nFlagged {df['flagged'].sum()} of {len(df)} pairs "
              f"({df['flagged'].mean():.1%}, 10× age-bucket median)")
        print(df["event"].value_counts().to_string())

        flagged_path = ANALYSIS_DIR / f"{group}_flagged.csv"
        df[df["flagged"]].sort_values("error_km", ascending=False).to_csv(flagged_path, index=False)
        logger.info("%s: flagged pairs saved to %s", group, flagged_path)

    held, changed = day_old_medians(frames)
    logger.info("Day-old median error: %.1f km held altitude, %.1f km changed (%.1fx)",
                held, changed, changed / held)

    chart_path = plot_errors(frames, Path("demo") / "prediction_error.png")
    logger.info("Chart saved to %s", chart_path)
