from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import requests
import logging

from config import setup_logging, RAW_DATA_DIR, GROUP_LIST, MAX_AGE, TS_FORMAT

logger = logging.getLogger(__name__)

def fetch_group(group: str) -> list[dict]:
    """
    Fetches the group data from the API.

    Args:
        group (str): The name of the group to fetch."""
    
    url = "https://celestrak.org/NORAD/elements/gp.php"
    response = requests.get(url, params={"GROUP": group, "FORMAT": "json"}, timeout=30)
    response.raise_for_status()  # Raise an error for bad responses
    return response.json()  # Assuming the API returns JSON data

def save_raw(group:str, records:list[dict]) -> Path:
    """
    Saves the raw group data to a JSON file.

    Args:
        group (str): The name of the group.
        records (list[dict]): The list of records to save.
    """
    timestamp = datetime.now(timezone.utc).strftime(TS_FORMAT)
    folder = RAW_DATA_DIR / group
    file_path = folder / f"{timestamp}.json"
    folder.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=4)

    return file_path

def latest_raw(group:str) -> Path | None:
    """
    Returns the path to the latest raw JSON file for the specified group.
    Returns None if no files are found.

    Args:
        group (str): The name of the group.
    """
    folder = RAW_DATA_DIR / group
    if not folder.exists():
        return None  # No data for this group yet

    # get JSON files in the folder, sorted by name (which includes timestamp)
    json_files = sorted(folder.glob("*.json"), reverse=True)
    if not json_files:
        return None  # No JSON files found for this group

    # return latest file (first in the sorted list)
    return json_files[0]

def file_age(path: Path) -> timedelta:
    """
    Returns the age of the file at the given path.

    Args:
        path (Path): The path to the file.

    Returns:
        timedelta: The age of the file.
    """

    # subtract the timestamp in the filename from the current time to get the file's age
    file_time = datetime.strptime(path.stem, TS_FORMAT).replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - file_time

def is_fresh(path: Path, max_age: timedelta) -> bool:
    """
    Checks if the file at the given path is fresh.

    Args:
        path (Path): The path to the file.
        max_age (timedelta): The maximum allowed age for the file.

    Returns:
        bool: True if the file is fresh, False otherwise.
    """
    if not path.exists():
        return False  # File does not exist

    return file_age(path) < max_age

if __name__ == "__main__":

    setup_logging()

    for group in GROUP_LIST:
        logger.info("%s: fetching from CelesTrak", group)
        latest = latest_raw(group)
        if latest is None or not is_fresh(latest, MAX_AGE):
            records = fetch_group(group)
            file_path = save_raw(group, records)
            logger.info("%s: saved %d records to %s", group, len(records), file_path)
        else:
            age = file_age(latest)
            minutes = int(age.total_seconds() // 60)
            logger.info("%s: cache is fresh (%d min old), skipping fetch", group, minutes)