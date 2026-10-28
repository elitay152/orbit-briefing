import json
from pathlib import Path
from datetime import datetime
import logging
import duckdb
import pandas as pd

from extract import latest_raw
from config import setup_logging, GROUP_LIST, DB_PATH, LAKE_DIR

# constants
REQUIRED_FIELDS = ['NORAD_CAT_ID', 'OBJECT_NAME', 'OBJECT_ID', 'EPOCH', 
                   'MEAN_MOTION', 'INCLINATION', 'ECCENTRICITY', 
                   'RA_OF_ASC_NODE', 'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 
                   'BSTAR', 'MEAN_MOTION_DOT', 'MEAN_MOTION_DDOT',
                   'CLASSIFICATION_TYPE', 'EPHEMERIS_TYPE', 'ELEMENT_SET_NO',
                   'REV_AT_EPOCH']
LAKE_COLUMNS = ["norad_cat_id", "object_name", "object_id", "epoch", "mean_motion",
                "inclination", "eccentricity", "ra_of_asc_node", "arg_of_pericenter",
                "mean_anomaly", "bstar", "mean_motion_dot", "mean_motion_ddot",
                "classification_type", "ephemeris_type", "element_set_no",
                "rev_at_epoch", "source_file",]
logger = logging.getLogger(__name__)

def read_raw(path: Path) -> list[dict]:
    """Read the raw data from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_record(record: dict) -> list[str]:
    """Validate a single record against the required fields.
    Returns a list of issues; empty if the record is valid.
    """
    
    missing_fields = [field for field in REQUIRED_FIELDS if record.get(field) is None]
    issues = []

    # check 1: Check if the record has all required fields
    if missing_fields:
        issues.append(f"missing required fields: {missing_fields}")

    # check 2: Mean motion should be a positive float
    mean_motion = record.get('MEAN_MOTION')
    if mean_motion is not None:
        try:
            mean_motion_value = float(mean_motion)
            if mean_motion_value <= 0:
                issues.append(f"non-positive MEAN_MOTION: {mean_motion}")
        except (ValueError, TypeError):
            issues.append(f"invalid MEAN_MOTION: {mean_motion}")

    # check 3: Epoch should be a valid datetime string in the expected format
    epoch = record.get('EPOCH')
    if epoch is not None:
        try:
            datetime.fromisoformat(epoch)
        except (ValueError, TypeError):
            issues.append(f"invalid EPOCH format: {epoch}")
    
    return issues

def validate(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Validate a list of records and separate them into valid and invalid lists.
    Returns a tuple of (valid_records, invalid_records)."""
    valid_records = []
    invalid_records = []

    for record in records:
        issues = validate_record(record)
        if not issues: 
            valid_records.append(record)
        else:
            logger.warning("Rejected NORAD_CAT_ID=%s: %s",
                           record.get("NORAD_CAT_ID"), issues)
            invalid_records.append({"record": record, "errors": issues})

    return valid_records, invalid_records

def create_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the orbital_elements table in the DuckDB database if it doesn't exist."""
    con.execute("""CREATE TABLE IF NOT EXISTS orbital_elements (
        norad_cat_id INTEGER, 
        object_name VARCHAR, 
        object_id VARCHAR,
        epoch TIMESTAMPTZ, 
        mean_motion DOUBLE, 
        inclination DOUBLE, 
        eccentricity DOUBLE, 
        ra_of_asc_node DOUBLE, 
        arg_of_pericenter DOUBLE, 
        mean_anomaly DOUBLE, 
        mean_motion_dot DOUBLE, 
        mean_motion_ddot DOUBLE,
        bstar DOUBLE, 
        classification_type VARCHAR,
        ephemeris_type INTEGER,
        element_set_no INTEGER,
        rev_at_epoch INTEGER,
        constellation VARCHAR,
        source_file VARCHAR, 
        loaded_at TIMESTAMPTZ DEFAULT current_timestamp,
        PRIMARY KEY (norad_cat_id, epoch))""")

def to_dataframe(records: list[dict], constellation: str, source_file: str) -> pd.DataFrame:
    """Lowercase columns, add lineage columns, parse epoch as UTC."""

    records_df = pd.DataFrame(records)
    records_df.columns = [col.lower() for col in records_df.columns]  # Convert column names to lowercase   
    records_df["constellation"] = constellation
    records_df["source_file"] = source_file
    records_df["epoch"] = pd.to_datetime(records_df["epoch"], utc=True)  # Ensure epoch is in UTC

    return records_df

def write_parquet(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                  constellation: str, snapshot: str) -> Path:
    """Write one snapshot to the lake; same snapshot → same file (idempotent)."""

    folder = LAKE_DIR / f"constellation={constellation}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"snapshot={snapshot}.parquet"
    con.execute(f"COPY (SELECT {', '.join(LAKE_COLUMNS)} FROM df) "
                f"TO '{path.as_posix()}' (FORMAT parquet)")

    return path

def load_records(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Insert a snapshot's rows into orbital_elements; returns the number of new rows."""
    cols = ", ".join(LAKE_COLUMNS + ["constellation"])

    prior_count = con.execute("SELECT COUNT(*) FROM orbital_elements").fetchone()[0]
    con.execute(f"INSERT OR IGNORE INTO orbital_elements ({cols}) SELECT {cols} FROM df")
    new_count = con.execute("SELECT COUNT(*) FROM orbital_elements").fetchone()[0]

    return new_count - prior_count


if __name__ == "__main__":

    setup_logging()

    with duckdb.connect(str(DB_PATH)) as con:
        create_table(con)
        for group in GROUP_LIST:
            latest_file = latest_raw(group)
    
            if latest_file is None:
                logger.warning("No raw data found for group %s", group)
                continue

            raw_data = read_raw(latest_file)
            logger.info("Loaded %d records from %s", len(raw_data), group)
            logger.debug("First record: %s", json.dumps(raw_data[0], indent=2))
            
            valid_records, invalid_records = validate(raw_data)
            if not valid_records:
                logger.warning("%s: no valid records, skipping", group)
                continue

            df = to_dataframe(valid_records, group, latest_file.name)
            parquet_path = write_parquet(con, df, group, latest_file.stem)
            inserted = load_records(con, df)
            logger.info("%s: %d valid, %d rejected, %d inserted, wrote %s",
                        group, len(valid_records),
                        len(invalid_records), inserted, parquet_path.name)
            