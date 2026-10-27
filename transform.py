import duckdb
from datetime import timezone
from skyfield.api import load, EarthSatellite

from extract import GROUP_LIST
from load import DB_PATH

# constants
LATEST_SQL = """
SELECT * FROM orbital_elements
WHERE constellation = ?
QUALIFY ROW_NUMBER() OVER(PARTITION BY norad_cat_id
ORDER BY epoch DESC) = 1
"""

OMM_FIELDS = [
    "OBJECT_NAME", "OBJECT_ID", "NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
    "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY",
    "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "CLASSIFICATION_TYPE",
    "EPHEMERIS_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH",
]

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


if __name__ == "__main__":

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        ts = load.timescale()
        
        for group in GROUP_LIST:
            elements = latest_elements(con, group)
            omm_elements = [to_omm(element) for element in elements]
            print(group, len(omm_elements))

            sat = EarthSatellite.from_omm(ts, omm_elements[0])
            print(sat)