"""Control charts of the orbit data.

- Laney p' chart: the share of satellites changing altitude between daily snapshots
- Individuals chart: how old the orbit data is when each snapshot is fetched

Run from the repository root. To chart the daily history, point LAKE_DIR at a copy of
the data branch's orbital_elements folder; by default this reads the local lake.
"""
import logging
import math
from pathlib import Path

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from orbit.analysis.theme import LIGHT
from orbit.config import setup_logging, ANALYSIS_DIR, LAKE_GLOB, DISPLAY_NAMES

logger = logging.getLogger(__name__)

# constants
IMR_FACTOR = 2.66          # standard individuals-chart constant: 3 / d2, with d2 = 1.128
D2 = 1.128                 # moving-range constant for subgroups of 2
RUN_LENGTH = 8             # this many points in a row on one side of the mean is a signal
MIN_BASELINE_POINTS = 25   # below this, limits are only preliminary
ALTITUDE_CHANGE_KM = 0.5   # a satellite counts as changed if it moved more than this
MARKER_MAX_POINTS = 60     # above this, charts draw lines without a dot per point

# One snapshot per UTC day (the latest), so the gaps being compared are about a day.
# Satellites missing from the previous snapshot aren't compared.
ALTITUDE_CHANGE_SQL = f"""
    WITH records AS (
        SELECT constellation, norad_cat_id,
               strptime(regexp_extract(source_file, '^[^.]+'), '%Y%m%dT%H%M%SZ') AS snapshot_time,
               cbrt(398600.4418 / pow(mean_motion * 2 * pi() / 86400, 2)) - 6378.137 AS altitude_km
        FROM read_parquet('{LAKE_GLOB}', hive_partitioning = true)
    ),
    daily AS (
        SELECT * FROM records
        QUALIFY dense_rank() OVER (
            PARTITION BY constellation, snapshot_time::DATE ORDER BY snapshot_time DESC
        ) = 1
    ),
    changes AS (
        SELECT constellation, snapshot_time,
               altitude_km - lag(altitude_km) OVER (
                   PARTITION BY constellation, norad_cat_id ORDER BY snapshot_time
               ) AS change_km
        FROM daily
    )
    SELECT constellation, snapshot_time,
           count(change_km) AS compared,
           count(*) FILTER (abs(change_km) > {ALTITUDE_CHANGE_KM}) AS changed,
           count(*) FILTER (change_km > {ALTITUDE_CHANGE_KM}) AS raised,
           count(*) FILTER (change_km < -{ALTITUDE_CHANGE_KM}) AS lowered
    FROM changes
    GROUP BY constellation, snapshot_time
    HAVING count(change_km) > 0
    ORDER BY constellation, snapshot_time
"""

# epoch() gives UTC seconds for both values, so the session time zone can't shift the age
SNAPSHOT_METRICS_SQL = f"""
    WITH records AS (
        SELECT constellation, norad_cat_id, epoch AS record_epoch,
               strptime(regexp_extract(source_file, '^[^.]+'), '%Y%m%dT%H%M%SZ') AS snapshot_time
        FROM read_parquet('{LAKE_GLOB}', hive_partitioning = true)
    )
    SELECT constellation, snapshot_time,
           count(DISTINCT norad_cat_id) AS satellites,
           median((epoch(snapshot_time) - epoch(record_epoch)) / 3600) AS median_age_hours
    FROM records
    GROUP BY constellation, snapshot_time
    ORDER BY constellation, snapshot_time
"""

def snapshot_metrics(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per constellation per snapshot, computed from the lake."""
    return con.execute(SNAPSHOT_METRICS_SQL).fetchdf()

def altitude_change_metrics(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per constellation per daily comparison: satellites compared and changed."""
    return con.execute(ALTITUDE_CHANGE_SQL).fetchdf()

def laney_limits(changed: list[int], compared: list[int]) -> dict:
    """Laney p' limits: a p-chart widened by the real point-to-point variation.

    A standard p-chart assumes satellites change independently, which makes its limits far
    too tight when thousands of satellites are compared. sigma_z measures how much wider the
    real variation is. It's floored at 1, so limits are never tighter than a standard p-chart.
    """
    if len(changed) < 2:
        raise ValueError("Control limits need at least 2 points")

    p_bar = sum(changed) / sum(compared)
    rates = [c / n for c, n in zip(changed, compared)]
    if p_bar in (0, 1):   # no variation to measure (e.g. no satellite ever changed): limits collapse
        return {"p_bar": p_bar, "sigma_z": 1.0, "rates": rates,
                "ucl": [p_bar] * len(rates), "lcl": [p_bar] * len(rates)}
    sigmas = [math.sqrt(p_bar * (1 - p_bar) / n) for n in compared]
    z_scores = [(p - p_bar) / s for p, s in zip(rates, sigmas)]
    moving_ranges = [abs(b - a) for a, b in zip(z_scores, z_scores[1:])]
    sigma_z = max(1.0, (sum(moving_ranges) / len(moving_ranges)) / D2)

    return {
        "p_bar": p_bar,
        "sigma_z": sigma_z,
        "rates": rates,
        "ucl": [p_bar + 3 * sigma_z * s for s in sigmas],
        "lcl": [max(0.0, p_bar - 3 * sigma_z * s) for s in sigmas],
    }

def rate_signals(limits: dict) -> list[bool]:
    """Flag rates outside their own limits (limits vary with the number compared)."""
    return [p > u or p < l for p, u, l in zip(limits["rates"], limits["ucl"], limits["lcl"])]

def individuals_limits(values: list[float]) -> dict[str, float]:
    """Center line and control limits from the average moving range; needs 2+ values."""
    if len(values) < 2:
        raise ValueError("Control limits need at least 2 values")

    center = sum(values) / len(values)
    moving_ranges = [abs(b - a) for a, b in zip(values, values[1:])]
    mr_bar = sum(moving_ranges) / len(moving_ranges)
    return {
        "center": center,
        "mr_bar": mr_bar,
        "ucl": center + IMR_FACTOR * mr_bar,
        "lcl": center - IMR_FACTOR * mr_bar,
    }

def find_signals(values: list[float], limits: dict[str, float]) -> list[bool]:
    """Flag points outside the limits, and points completing a run on one side of the mean."""
    signals = [v > limits["ucl"] or v < limits["lcl"] for v in values]

    run_side, run_length = 0, 0
    for i, value in enumerate(values):
        side = (value > limits["center"]) - (value < limits["center"])
        run_length = run_length + 1 if side == run_side and side != 0 else 1
        run_side = side
        if side != 0 and run_length >= RUN_LENGTH:
            signals[i] = True

    return signals

def plural(count: int, word: str) -> str:
    """'1 signal', '3 signals'."""
    return f"{count:,} {word}" + ("" if count == 1 else "s")

def marker_size(points: int) -> float:
    """Dots on each point while they're few enough to see; just the line once the history is long."""
    return 6 if points <= MARKER_MAX_POINTS else 0

def line_width(points: int) -> float:
    return 2 if points <= MARKER_MAX_POINTS else 1.2

def set_date_axis(ax) -> None:
    """Date ticks that stay readable from a week of history to years of it."""
    locator = mdates.AutoDateLocator(minticks=3, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, show_offset=False))

def plot_p_chart(metrics: pd.DataFrame, path: Path, theme: dict = LIGHT) -> Path:
    """Laney p' chart of the share of satellites changing altitude, one panel per constellation."""
    groups = list(metrics.groupby("constellation"))
    fig, axes = plt.subplots(1, len(groups), figsize=(11, 4.4), sharey=True, squeeze=False)
    fig.patch.set_facecolor(theme["surface"])

    for ax, (group, df) in zip(axes[0], groups):
        limits = laney_limits(df["changed"].tolist(), df["compared"].tolist())
        signals = rate_signals(limits)
        times = df["snapshot_time"]
        rates = [r * 100 for r in limits["rates"]]
        ucl = [u * 100 for u in limits["ucl"]]
        lcl = [l * 100 for l in limits["lcl"]]

        ax.set_facecolor(theme["surface"])
        ax.plot(times, ucl, color=theme["muted"], linewidth=1, linestyle="--")
        ax.plot(times, lcl, color=theme["muted"], linewidth=1, linestyle="--")
        ax.axhline(limits["p_bar"] * 100, color=theme["muted"], linewidth=1)
        ax.plot(times, rates, color=theme["line"], linewidth=line_width(len(df)), marker="o",
                markersize=marker_size(len(df)),
                markeredgecolor=theme["surface"], markeredgewidth=1)

        flagged_times = [t for t, s in zip(times, signals) if s]
        flagged_rates = [r for r, s in zip(rates, signals) if s]
        ax.scatter(flagged_times, flagged_rates, s=90, color=theme["signal"], marker="D",
                   edgecolors=theme["surface"], linewidths=1, zorder=3)

        for value, label in ((ucl[-1], "UCL"), (limits["p_bar"] * 100, "Mean"), (lcl[-1], "LCL")):
            ax.annotate(f"{label} {value:.1f}%", xy=(1, value),
                        xycoords=("axes fraction", "data"), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=9, color=theme["ink_2"])

        ax.set_title(f"{DISPLAY_NAMES.get(group, group)}  ·  {plural(len(df), 'comparison')}, "
                     f"{plural(sum(signals), 'signal')}", loc="left", fontsize=11, color=theme["ink"])
        set_date_axis(ax)
        ax.grid(True, axis="y", color=theme["grid"], linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme["axis"])
        ax.tick_params(colors=theme["muted"])

    # after all panels are drawn, so the top limit includes every point
    axes[0][0].set_ylim(bottom=0)
    axes[0][0].set_ylabel(f"Satellites changing more than {ALTITUDE_CHANGE_KM} km (%)", color=theme["ink_2"])
    points = metrics.groupby("constellation").size().min()
    status = "preliminary limits" if points < MIN_BASELINE_POINTS else "baseline limits"
    fig.suptitle(f"Share of satellites changing altitude each day: Laney p′ chart ({status})",
                 x=0.01, ha="left", fontsize=13, color=theme["ink"])
    # manual margins: tight_layout can't account for the limit labels outside the axes
    fig.subplots_adjust(left=0.07, right=0.92, top=0.82, bottom=0.1, wspace=0.3)
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

def plot_control_chart(metrics: pd.DataFrame, path: Path, theme: dict = LIGHT) -> Path:
    """Individuals chart of median data age, one panel per constellation."""
    groups = list(metrics.groupby("constellation"))
    fig, axes = plt.subplots(1, len(groups), figsize=(11, 4.4), sharey=True, squeeze=False)
    fig.patch.set_facecolor(theme["surface"])

    for ax, (group, df) in zip(axes[0], groups):
        values = df["median_age_hours"].tolist()
        times = df["snapshot_time"]
        limits = individuals_limits(values)
        signals = find_signals(values, limits)

        ax.set_facecolor(theme["surface"])
        ax.plot(times, values, color=theme["line"], linewidth=line_width(len(values)), marker="o",
                markersize=marker_size(len(values)),
                markeredgecolor=theme["surface"], markeredgewidth=1)

        flagged = df[signals]
        ax.scatter(flagged["snapshot_time"], flagged["median_age_hours"], s=90, color=theme["signal"],
                   marker="D", edgecolors=theme["surface"], linewidths=1, zorder=3,
                   label=f"Signal ({len(flagged)})")

        for name, label, style in (("ucl", "UCL", "--"), ("center", "Mean", "-"), ("lcl", "LCL", "--")):
            ax.axhline(limits[name], color=theme["muted"], linewidth=1, linestyle=style)
            ax.annotate(f"{label} {limits[name]:.1f}", xy=(1, limits[name]),
                        xycoords=("axes fraction", "data"), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=9, color=theme["ink_2"])

        ax.set_title(f"{DISPLAY_NAMES.get(group, group)}  ·  {plural(len(values), 'snapshot')}, "
                     f"{plural(sum(signals), 'signal')}", loc="left", fontsize=11, color=theme["ink"])
        set_date_axis(ax)
        ax.grid(True, axis="y", color=theme["grid"], linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme["axis"])
        ax.tick_params(colors=theme["muted"])

    axes[0][0].set_ylabel("Median age of orbit data (hours)", color=theme["ink_2"])
    points = metrics.groupby("constellation").size().min()
    status = "preliminary limits" if points < MIN_BASELINE_POINTS else "baseline limits"
    fig.suptitle(f"Is data freshness stable? Individuals control chart ({status})",
                 x=0.01, ha="left", fontsize=13, color=theme["ink"])
    fig.tight_layout(w_pad=4)
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

def run_spc(p_chart_path: Path, freshness_path: Path,
            theme: dict = LIGHT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute both charts' metrics from the lake, log a summary, and save both charts.

    Returns (snapshot metrics, altitude-change metrics).
    """
    with duckdb.connect() as con:
        metrics = snapshot_metrics(con)
        changes = altitude_change_metrics(con)

    for group, df in changes.groupby("constellation"):
        limits = laney_limits(df["changed"].tolist(), df["compared"].tolist())
        logger.info("%s: %d comparisons, mean %.1f%% changed, sigma_z %.2f, %d raised, %d lowered, %d signals",
                    group, len(df), limits["p_bar"] * 100, limits["sigma_z"],
                    df["raised"].sum(), df["lowered"].sum(), sum(rate_signals(limits)))

    logger.info("Chart saved to %s", plot_p_chart(changes, p_chart_path, theme))

    for group, df in metrics.groupby("constellation"):
        values = df["median_age_hours"].tolist()
        limits = individuals_limits(values)
        signals = find_signals(values, limits)
        logger.info("%s: %d snapshots, mean %.1fh, limits %.1f to %.1f, %d signals",
                    group, len(values), limits["center"], limits["lcl"], limits["ucl"], sum(signals))
        if len(values) < MIN_BASELINE_POINTS:
            logger.warning("%s: only %d snapshots; limits are preliminary until %d",
                           group, len(values), MIN_BASELINE_POINTS)

    logger.info("Chart saved to %s", plot_control_chart(metrics, freshness_path, theme))
    return metrics, changes

if __name__ == "__main__":
    setup_logging()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    run_spc(Path("demo") / "spc_altitude_change.png", ANALYSIS_DIR / "spc_data_age.png")
