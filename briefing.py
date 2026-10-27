import logging
from skyfield.api import load, wgs84
import duckdb
from datetime import datetime

from transform import compute_peaks
from config import LAT, LON, LOCATION_NAME, DB_PATH

# constants
DIRECTIONS = ["north", "northeast", "east", "southeast", "south",
            "southwest", "west", "northwest"]
DISPLAY_NAMES = {'kuiper': 'Amazon Leo',
                 'starlink': 'Starlink'}

def compass(azimuth: float) -> str:
    """
    Convert azimuth in degrees to compass direction.
    """

    degrees = 360 / len(DIRECTIONS)  # degrees per direction
    index = round(azimuth / degrees) % len(DIRECTIONS)
    return DIRECTIONS[index]

def spoken_time(dt: datetime) -> str:
    """Format a datetime for speech, e.g. '7:26 PM UTC'."""
    return dt.strftime("%I:%M %p").lstrip("0") + " UTC"

def spoken_name(name: str) -> str:
    """Format satellite names for speech."""
    try:
        prefix, number = name.split("-", 1) # split at the first dash
    except:
        return name

    return f"{prefix.title()} {int(number)}"

def build_script(peaks_by_group: dict, LOCATION_NAME: str) -> str:
    """Develops a briefing script from the peaks data for each group."""

    script = []

    greeting = f"Here's your satellite pass briefing for {LOCATION_NAME} for the next hour."
    script.append(greeting)

    for group, peaks in peaks_by_group.items():
        if not peaks:
            script.append(f"{DISPLAY_NAMES.get(group, group)} has no passes in the next hour.")
            continue

        highest = max(peaks, key=lambda p: p["altitude"])

        script.append(f"{DISPLAY_NAMES.get(group, group)} satellites make {len(peaks):,} passes in the next hour.")
        script.append(f"The highest is {spoken_name(highest['name'])}, reaching {highest['altitude']:.0f} degrees "
                      f"in the {compass(highest['azimuth'])} at {spoken_time(highest['time'])}, about "
                      f"{highest['distance_km']:,.0f} kilometers away.")

    return "\n".join(script)

if __name__ == "__main__":
    logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        ts = load.timescale()
        observer = wgs84.latlon(LAT, LON)
        t0 = ts.now()
        peaks_by_group = compute_peaks(con, ts, observer, t0, t0 + 1/24)

        print(build_script(peaks_by_group, LOCATION_NAME))