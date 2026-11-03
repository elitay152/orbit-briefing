"""World map of every tracked satellite at the latest snapshot, highlighting those whose
altitude changed since the previous snapshot.

Run from the repository root. Point LAKE_DIR at a copy of the data branch's
orbital_elements folder to map the daily history; by default this reads the local lake.
"""
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np
import pandas as pd
from skyfield.api import load, wgs84, EarthSatellite, Timescale

from orbit.analysis.prediction_error import altitude_km
from orbit.analysis.spc import ALTITUDE_CHANGE_KM
from orbit.config import setup_logging, DISPLAY_NAMES, LAKE_GLOB, TS_FORMAT
from orbit.pipeline.transform import to_omm

logger = logging.getLogger(__name__)

# constants
LAND_GEOJSON = Path(__file__).resolve().parents[2] / "assets" / "ne_110m_land.geojson"

# dark theme: the same hues as the light charts, stepped for a dark background
SPACE = "#0e1420"
LAND = "#222b3a"
COAST = "#3a4558"
INK = "#f0efec"
INK_2 = "#c3c2b7"
MUTED = "#8d93a0"
HIGHLIGHT = "#f0efec"
SERIES_COLORS = {"kuiper": "#3987e5", "starlink": "#d95926"}
DRAW_ORDER = ["starlink", "kuiper"]   # Starlink first (many dots), Leo on top so it stays visible
DOT_SIZE = {"starlink": 3, "kuiper": 14}

# each satellite's newest record in the newest two snapshots of each constellation
SNAPSHOT_PAIR_SQL = f"""
    WITH records AS (
        SELECT *, dense_rank() OVER (PARTITION BY constellation ORDER BY source_file DESC) AS snapshot_rank
        FROM read_parquet('{LAKE_GLOB}', hive_partitioning = true)
    )
    SELECT * FROM records
    WHERE snapshot_rank <= 2
    QUALIFY row_number() OVER (
        PARTITION BY constellation, snapshot_rank, norad_cat_id ORDER BY epoch DESC
    ) = 1
"""

def latest_and_previous(con: duckdb.DuckDBPyConnection) -> tuple[list[dict], list[dict]]:
    """Rows from each constellation's latest snapshot, and from its previous one."""
    cursor = con.execute(SNAPSHOT_PAIR_SQL)
    columns = [col[0] for col in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    latest = [r for r in rows if r["snapshot_rank"] == 1]
    previous = [r for r in rows if r["snapshot_rank"] == 2]
    return latest, previous

def changed_flags(latest: list[dict], previous: list[dict]) -> list[bool]:
    """For each latest row: did its altitude change by more than ALTITUDE_CHANGE_KM?

    Satellites missing from the previous snapshot count as unchanged.
    """
    previous_mean_motion = {(r["constellation"], r["norad_cat_id"]): r["mean_motion"] for r in previous}
    flags = []
    for row in latest:
        before = previous_mean_motion.get((row["constellation"], row["norad_cat_id"]))
        flags.append(before is not None
                     and abs(altitude_km(row["mean_motion"]) - altitude_km(before)) > ALTITUDE_CHANGE_KM)
    return flags

def snapshot_time(rows: list[dict]) -> datetime:
    """Fetch time of the newest snapshot among the rows, from its source file name."""
    stamp = max(r["source_file"] for r in rows).split(".")[0]
    return datetime.strptime(stamp, TS_FORMAT).replace(tzinfo=timezone.utc)

def subpoint(row: dict, ts: Timescale, when: datetime) -> tuple[float, float] | None:
    """(latitude, longitude) of the point under the satellite, or None if SGP4 fails."""
    sat = EarthSatellite.from_omm(ts, to_omm(row))
    point = wgs84.subpoint_of(sat.at(ts.from_datetime(when)))
    lat, lon = float(point.latitude.degrees), float(point.longitude.degrees)
    if math.isnan(lat) or math.isnan(lon):
        return None
    return lat, lon

def map_points(con: duckdb.DuckDBPyConnection, ts: Timescale) -> tuple[pd.DataFrame, datetime]:
    """One row per satellite in the latest snapshot: position, and whether its altitude changed."""
    latest, previous = latest_and_previous(con)
    when = snapshot_time(latest)

    points = []
    for row, changed in zip(latest, changed_flags(latest, previous)):
        position = subpoint(row, ts, when)
        if position is None:
            logger.warning("No position for %s; skipping", row["object_name"])
            continue
        points.append({"constellation": row["constellation"], "norad_cat_id": row["norad_cat_id"],
                       "lat": position[0], "lon": position[1], "changed": changed})

    return pd.DataFrame(points), when

def draw_land(ax, geojson_path: Path) -> None:
    """Fill the land polygons from a GeoJSON file."""
    world = json.loads(geojson_path.read_text(encoding="utf-8"))
    for feature in world["features"]:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for polygon in polygons:
            ax.add_patch(Polygon(polygon[0], closed=True, facecolor=LAND, edgecolor=COAST,
                                 linewidth=0.4, zorder=1))

def plot_map(points: pd.DataFrame, when: datetime, path: Path, land_path: Path = LAND_GEOJSON) -> Path:
    """Dark world map: every satellite as a dot, changed satellites ringed."""
    fig = plt.figure(figsize=(12, 7))
    fig.patch.set_facecolor(SPACE)
    ax = fig.add_axes([0.03, 0.12, 0.94, 0.70])
    ax.set_facecolor(SPACE)
    draw_land(ax, land_path)

    groups = [g for g in DRAW_ORDER if g in set(points["constellation"])]
    groups += sorted(set(points["constellation"]) - set(groups))
    for group in groups:
        df = points[points["constellation"] == group]
        changed = df["changed"].to_numpy(dtype=bool)
        color = SERIES_COLORS.get(group, MUTED)
        size = DOT_SIZE.get(group, 6)
        ax.scatter(df["lon"][~changed], df["lat"][~changed], s=size, color=color,
                   alpha=0.75 if size < 6 else 1.0, linewidths=0, zorder=2,
                   label=f"{DISPLAY_NAMES.get(group, group)}  ({len(df):,})")
        ax.scatter(df["lon"][changed], df["lat"][changed], s=size * 3 + 6, facecolor=color,
                   edgecolor=HIGHLIGHT, linewidths=0.8, zorder=3)

    ax.scatter([], [], s=28, facecolor="none", edgecolor=HIGHLIGHT, linewidths=0.8,
               label=f"Changed altitude since the previous snapshot  ({int(points['changed'].sum()):,})")

    ax.set_xlim(-180, 180)
    ax.set_ylim(-75, 80)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.legend(loc="lower left", bbox_to_anchor=(0, -0.14), ncol=3, frameon=False, fontsize=11,
              labelcolor=INK_2, markerscale=2.2, handletextpad=0.4, columnspacing=2)

    fig.text(0.03, 0.93, f"Every Amazon Leo and Starlink satellite I'm tracking: {len(points):,} of them",
             fontsize=20, fontweight="bold", color=INK, va="top")
    fig.text(0.03, 0.865,
             f"Positions at {when:%b} {when.day}, {when:%Y} {when:%H:%M} UTC, "
             "computed from public CelesTrak orbit data by my daily pipeline",
             fontsize=12, color=INK_2, va="top")
    fig.text(0.97, 0.035, "github.com/elitay152/orbit-briefing", fontsize=10, color=MUTED, ha="right")

    fig.savefig(path, dpi=150, facecolor=SPACE)
    plt.close(fig)
    return path

if __name__ == "__main__":
    setup_logging()

    with duckdb.connect() as con:
        points, when = map_points(con, load.timescale())

    for group, df in points.groupby("constellation"):
        logger.info("%s: %d satellites, %d changed altitude", group, len(df), df["changed"].sum())

    path = plot_map(points, when, Path("demo") / "satellite_map.png")
    logger.info("Map saved to %s", path)
