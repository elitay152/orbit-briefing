# config.py
from datetime import timedelta
from pathlib import Path
import os
import logging

from dotenv import load_dotenv

load_dotenv()

# Paths
DATA_DIR = Path(__file__).parent / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "orbit.duckdb"
LAKE_DIR = Path(os.environ.get("LAKE_DIR", DATA_DIR / "lake" / "orbital_elements"))

# Extract
GROUP_LIST = ["kuiper", "starlink"]
MAX_AGE = timedelta(hours=2)
TS_FORMAT = "%Y%m%dT%H%M%SZ"

# Location (from .env)
LAT = float(os.environ["LAT"])
LON = float(os.environ["LON"])
LOCATION_NAME = os.environ["LOCATION_NAME"]
MIN_ALTITUDE_DEG = 10.0

# TTS
TTS_BACKEND = os.environ.get("TTS_BACKEND", "pyttsx3")
BRIEFINGS_DIR = DATA_DIR / "briefings"

# functions
def setup_logging(level=logging.INFO):
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("comtypes").setLevel(logging.WARNING)