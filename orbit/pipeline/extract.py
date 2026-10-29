from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

from orbit.config import setup_logging, RAW_DATA_DIR, GROUP_LIST, MAX_AGE, TS_FORMAT

logger = logging.getLogger(__name__)

# constants
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"

# retry transient server errors (5xx) with backoff: waits of ~2s, 4s, 8s;
# 4xx errors (e.g. a 403 rate-limit block) are never retried
RETRY = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,   # hand the final response back so raise_for_status reports it
)

def make_session(retry: Retry = RETRY) -> requests.Session:
    """Return a requests session that retries transient server errors."""
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session

def fetch_group(group: str, session: requests.Session, url: str = CELESTRAK_URL) -> list[dict]:
    """
    Fetches the group data from the API, retrying transient server errors.

    Args:
        group (str): The name of the group to fetch.
        session (requests.Session): Session from make_session(), so retries apply.
        url (str): The CelesTrak GP endpoint.
    """
    response = session.get(url, params={"GROUP": group, "FORMAT": "json"}, timeout=30)
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

def extract_all(groups: list[str], session: requests.Session) -> list[str]:
    """Fetch and save each group that isn't fresh; one group's failure doesn't stop the others.

    Returns the names of the groups that failed.
    """
    failed = []
    for group in groups:
        latest = latest_raw(group)
        if latest is not None and is_fresh(latest, MAX_AGE):
            minutes = int(file_age(latest).total_seconds() // 60)
            logger.info("%s: cache is fresh (%d min old), skipping fetch", group, minutes)
            continue

        logger.info("%s: fetching from CelesTrak", group)
        try:
            records = fetch_group(group, session)
        except requests.RequestException as e:
            logger.error("%s: fetch failed after retries: %s", group, e)
            failed.append(group)
            continue

        file_path = save_raw(group, records)
        logger.info("%s: saved %d records to %s", group, len(records), file_path)

    return failed

if __name__ == "__main__":

    setup_logging()

    failed = extract_all(GROUP_LIST, make_session())
    if failed:
        logger.error("Extract failed for: %s", ", ".join(failed))
        sys.exit(1)   # mark the run as failed so it gets noticed