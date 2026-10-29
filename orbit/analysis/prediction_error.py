import duckdb
import logging
import math
from pathlib import Path
from itertools import groupby, pairwise
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from skyfield.api import load, EarthSatellite, Timescale

from orbit.pipeline.transform import to_omm
from orbit.config import setup_logging, LAKE_GLOB, GROUP_LIST, ANALYSIS_DIR, DISPLAY_NAMES

# constants
EARTH_MU = 398600.4418       # Earth's gravitational constant, km³/s²
EARTH_RADIUS_KM = 6378.137
MANEUVER_ALT_KM = 0.5   # altitude change (km) needed to call a flagged pair raising/lowering

EVENT_STYLES = {
    # event:        (color,     marker, label)
    "raising":     ("#2a78d6", "^",    "Raising"),
    "lowering":    ("#eb6834", "v",    "Lowering"),
    "small/unclear": ("#1baf7a", "D",    "Small / unclear"),
}

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

def plot_errors(frames: dict[str, pd.DataFrame], path: Path) -> Path:
    """Scatter of prediction error vs. element age, one panel per constellation."""
    fig, axes = plt.subplots(1, len(frames), figsize=(11, 4.8), sharex=True, sharey=True)
    fig.patch.set_facecolor("#fcfcfb")

    for ax, (group, df) in zip(axes, frames.items()):
        ax.set_facecolor("#fcfcfb")

        normal = df[df["event"] == "normal"]
        ax.scatter(normal["age_days"], normal["error_km"],
                   s=8, color="#c3c2b7", alpha=0.5, linewidths=0, label="Normal")

        for event, (color, marker, label) in EVENT_STYLES.items():
            subset = df[df["event"] == event]
            ax.scatter(subset["age_days"], subset["error_km"],
                       s=30, color=color, marker=marker,
                       edgecolors="#fcfcfb", linewidths=0.6,   # thin ring so overlapping points stay distinct
                       label=label)

        counts = df["event"].value_counts()
        ax.set_title(
            f"{DISPLAY_NAMES.get(group, group)}  ·  "
            f"{counts.get('raising', 0)} raising, {counts.get('lowering', 0)} lowering, "
            f"{counts.get('small/unclear', 0)} small/unclear",
            loc="left", fontsize=11, color="#0b0b0b")

        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
        ax.set_xlabel("Age of older orbit record (days)", color="#52514e")
        ax.grid(True, which="major", color="#e1e0d9", linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#c3c2b7")
        ax.tick_params(colors="#898781")
        ax.tick_params(which="minor", length=0)

    # after all panels are drawn, so the limits include every point
    axes[0].set_ylim(bottom=0.05)
    axes[0].set_xlim(left=0)
    axes[0].set_ylabel("Position error (km, log scale)", color="#52514e")

    # one shared legend for both panels
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False,
               fontsize=10, markerscale=1.5)

    fig.suptitle("How far off is yesterday's orbit? Prediction error vs. age",
                 x=0.01, ha="left", fontsize=13, color="#0b0b0b")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

if __name__ == "__main__":

    setup_logging()
    ts = load.timescale()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["norad_cat_id", "object_name", "age_days", "error_km", "altitude_change_km", "event"]

    # 1. query everything, then close the connection
    with duckdb.connect() as con:
        records_by_group = {group: all_elements(con, group) for group in GROUP_LIST}

    # 2. compute and report per constellation
    frames = {}
    for group, records in records_by_group.items():
        errors = prediction_errors(records, ts, group)
        logger.info("%s: %d records, %d pairs", group, len(records), len(errors))

        df = pd.DataFrame(errors)
        df["age_bucket"] = df["age_days"].round()

        # flag first, then classify (classify reads "flagged")
        bucket_median = df.groupby("age_bucket")["error_km"].transform("median")
        df["flagged"] = df["error_km"] > 10 * bucket_median
        df["event"] = df.apply(classify, axis=1)

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

        frames[group] = df

    # 3. chart both constellations
    chart_path = plot_errors(frames, Path("demo") / "prediction_error.png")
    logger.info("Chart saved to %s", chart_path)