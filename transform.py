import duckdb
from datetime import timezone
from skyfield.api import load, EarthSatellite, wgs84
import time
import logging

from config import setup_logging, GROUP_LIST, LAT, LON, LOCATION_NAME, MIN_ALTITUDE_DEG, DB_PATH, LAKE_DIR

LAKE_GLOB = (LAKE_DIR / "*" / "*.parquet").as_posix()

LATEST_SQL = f"""
SELECT * FROM read_parquet('{LAKE_GLOB}', hive_partitioning = true)
WHERE constellation = ?
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY norad_cat_id
    ORDER BY epoch DESC, source_file DESC
) = 1
"""

OMM_FIELDS = [
    "OBJECT_NAME", "OBJECT_ID", "NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
    "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY",
    "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "CLASSIFICATION_TYPE",
    "EPHEMERIS_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH",
]

logger = logging.getLogger(__name__)

def latest_elements(con: duckdb.DuckDBPyConnection,
                    constellation: str) -> list[dict]:
    """Return the latest orbital elements for a given group from the DuckDB database."""

    cursor = con.execute(LATEST_SQL, [constellation])
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

def to_omm(row: dict) -> dict:
    """Convert a database row to an OMM dictionary."""
    omm_dict = {field: row[field.lower()] for field in OMM_FIELDS}
    omm_dict["EPOCH"] = omm_dict["EPOCH"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return omm_dict

def find_peaks(sat, observer, t0, t1) -> list[dict]:
    """Find the peaks of visibility for a satellite between two times."""
    
    # find rise/peak/set events above the minimum altitude
    times, events = sat.find_events(observer, t0, t1, altitude_degrees=MIN_ALTITUDE_DEG)

    peaks = []
    for t, event in zip(times, events):
        if event != 1:
            continue  # keep only peaks (event == 1)

        alt, az, distance = (sat - observer).at(t).altaz()
        peaks.append({
            "name": sat.name,
            "norad_id": sat.model.satnum,
            "time": t.utc_datetime(),
            "altitude": alt.degrees,
            "azimuth": az.degrees,
            "distance_km": distance.km
        })

    return peaks

def compute_peaks(con: duckdb.DuckDBPyConnection,
                    ts, observer, t0, t1) -> dict[str, list[dict]]:
    """Return each group's peaks over the observer between t0 and t1, sorted by time."""
    peaks_by_group = {}
    
    for group in GROUP_LIST:
        start = time.perf_counter()  # start the timer for this group

        elements = latest_elements(con, group)
        sats = [EarthSatellite.from_omm(ts, to_omm(e)) for e in elements]

        peaks = []
        for i, sat in enumerate(sats):
            if i and i % 1000 == 0:
                logger.debug("%s: %d/%d satellites checked", group, i, len(sats))
            peaks.extend(find_peaks(sat, observer, t0, t1))

        peaks.sort(key=lambda p: p["time"])
        peaks_by_group[group] = peaks
        elapsed = time.perf_counter() - start
        logger.info("%s: %d peaks from %d satellites in %.1fs",
                    group, len(peaks), len(sats), elapsed)
        
    return peaks_by_group

if __name__ == "__main__":

    setup_logging()

    # connect to database and find peaks for each group
    with duckdb.connect() as con:
        ts = load.timescale()
        observer = wgs84.latlon(LAT, LON)
        t0 = ts.now()
        t1 = t0 + 1/24  # 1 hour later

        peaks_by_group = compute_peaks(con, ts, observer, t0, t1)
        # debug preview of peaks for each group
        for group, peaks in peaks_by_group.items():
            logger.debug("Next %s peaks over %s:", group, LOCATION_NAME)
            for p in peaks[:5]:
                logger.debug("%s UTC  %s  %.0f° alt, %.0f° az, %.0f km",
                             f"{p['time']:%H:%M}", p["name"],
                             p["altitude"], p["azimuth"], p["distance_km"])