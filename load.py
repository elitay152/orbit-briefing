import json
from pathlib import Path
from datetime import datetime
import logging
import duckdb
import pandas as pd

from extract import latest_raw, GROUP_LIST, DATA_DIR

# constants
DB_PATH = DATA_DIR / "orbit.duckdb"
REQUIRED_FIELDS = ['NORAD_CAT_ID', 'OBJECT_NAME', 'EPOCH', 'MEAN_MOTION', 'INCLINATION', 'ECCENTRICITY', 'RA_OF_ASC_NODE', 'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'BSTAR']
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
        epoch TIMESTAMPTZ, 
        mean_motion DOUBLE, 
        inclination DOUBLE, 
        eccentricity DOUBLE, 
        ra_of_asc_node DOUBLE, 
        arg_of_pericenter DOUBLE, 
        mean_anomaly DOUBLE, 
        bstar DOUBLE, 
        constellation VARCHAR,
        source_file VARCHAR, 
        loaded_at TIMESTAMPTZ DEFAULT current_timestamp,
        PRIMARY KEY (norad_cat_id, epoch))""")

def load_records(con: duckdb.DuckDBPyConnection, 
                 records: list[dict], 
                 constellation: str, 
                 source_file: str) -> int:
    """Load valid records into the DuckDB database.
    Returns the number of records inserted."""

    if not records:
        return 0  # No records to insert

    records_df = pd.DataFrame(records)
    records_df.columns = [col.lower() for col in records_df.columns]  # Convert column names to lowercase   
    records_df["constellation"] = constellation
    records_df["source_file"] = source_file
    records_df["epoch"] = pd.to_datetime(records_df["epoch"], utc=True)  # Ensure epoch is in UTC

    # Insert records into the database
    prior_count = con.execute("SELECT COUNT(*) FROM orbital_elements").fetchone()[0]
    con.execute("""INSERT OR IGNORE INTO orbital_elements (
            norad_cat_id, object_name, epoch, mean_motion, inclination, eccentricity, 
            ra_of_asc_node, arg_of_pericenter, mean_anomaly, bstar, constellation, source_file
        ) SELECT
            norad_cat_id, object_name, epoch, mean_motion, inclination, eccentricity,
            ra_of_asc_node, arg_of_pericenter, mean_anomaly, bstar, constellation, source_file
        FROM records_df""")
    new_count = con.execute("SELECT COUNT(*) FROM orbital_elements").fetchone()[0]

    return new_count - prior_count


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
            inserted = load_records(con, valid_records, group, latest_file.name)
            logger.info("%s: %d valid, %d rejected, %d inserted", group, len(valid_records), len(invalid_records), inserted)    
