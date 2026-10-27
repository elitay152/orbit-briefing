# config.py
from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

# Paths
DATA_DIR = Path(__file__).parent / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "orbit.duckdb"

# Extract
GROUP_LIST = ["kuiper", "starlink"]
MAX_AGE = timedelta(hours=2)
TS_FORMAT = "%Y%m%dT%H%M%SZ"

# Location (from .env)
LAT = float(os.environ["LAT"])
LON = float(os.environ["LON"])
LOCATION_NAME = os.environ["LOCATION_NAME"]
MIN_ALTITUDE_DEG = 10.0