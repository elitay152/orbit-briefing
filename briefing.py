import logging
from skyfield.api import load, wgs84
import duckdb
from datetime import datetime, timezone
from pathlib import Path
import pyttsx3

from transform import compute_peaks
from config import setup_logging, LAT, LON, LOCATION_NAME, TS_FORMAT, BRIEFINGS_DIR, TTS_BACKEND, TIMEZONE

# constants
DIRECTIONS = ["north", "northeast", "east", "southeast", "south",
            "southwest", "west", "northwest"]
DISPLAY_NAMES = {'kuiper': 'Amazon Leo',
                 'starlink': 'Starlink'}

logger = logging.getLogger(__name__)

def compass(azimuth: float) -> str:
    """
    Convert azimuth in degrees to compass direction.
    """

    degrees = 360 / len(DIRECTIONS)  # degrees per direction
    index = round(azimuth / degrees) % len(DIRECTIONS)
    return DIRECTIONS[index]

def spoken_time(dt: datetime, tz:timezone) -> str:
    """Format a datetime for speech, e.g. '7:26 PM UTC'. Converts to local timezone."""
    local = dt.astimezone(tz)
    return local.strftime("%I:%M %p %Z").lstrip("0")

def spoken_name(name: str) -> str:
    """Format satellite names for speech."""
    try:
        prefix, number = name.split("-", 1) # split at the first dash
        return f"{prefix.title()} {int(number)}"
    except ValueError:
        return name

def build_script(peaks_by_group: dict, location: str) -> str:
    """Develops a briefing script from the peaks data for each group."""

    script = []

    greeting = f"Here's your satellite pass briefing for {location} for the next hour."
    script.append(greeting)

    for group, peaks in peaks_by_group.items():
        if not peaks:
            script.append(f"{DISPLAY_NAMES.get(group, group)} has no passes in the next hour.")
            continue

        highest = max(peaks, key=lambda p: p["altitude"])

        script.append(f"{DISPLAY_NAMES.get(group, group)} satellites make {len(peaks):,} passes in the next hour.")
        script.append(f"The highest is {spoken_name(highest['name'])}, reaching {highest['altitude']:.0f} degrees "
                      f"in the {compass(highest['azimuth'])} at {spoken_time(highest['time'], TIMEZONE)}, about "
                      f"{highest['distance_km']:,.0f} kilometers away.")

    return "\n".join(script)

def synthesize_pyttsx3(text: str, base_path: Path) -> Path:
    """Speak text with the offline system voice; returns the .wav path."""
    out_path = base_path.with_suffix(".wav")
    engine = pyttsx3.init()
    engine.save_to_file(text, str(out_path))
    engine.runAndWait()
    return out_path

def save_transcript(text: str, base_path: Path) -> Path:
    """Write the briefing text next to the audio; returns the .txt path."""
    transcript_path = base_path.with_suffix(".txt")
    transcript_path.write_text(text, encoding="utf-8")
    return transcript_path

def save_briefing(text: str) -> Path:
    """Save the transcript and audio for a briefing; returns the audio path."""
    
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    base_path = BRIEFINGS_DIR / datetime.now(timezone.utc).strftime(TS_FORMAT)

    transcript_path = save_transcript(text, base_path)
    logger.info("Transcript saved to %s", transcript_path)

    if TTS_BACKEND == "pyttsx3":
        return synthesize_pyttsx3(text, base_path)
    else:
        raise ValueError(f"Unknown TTS_BACKEND: {TTS_BACKEND}.")

if __name__ == "__main__":
    setup_logging()

    with duckdb.connect() as con:
        ts = load.timescale()
        observer = wgs84.latlon(LAT, LON)
        t0 = ts.now()
        peaks_by_group = compute_peaks(con, ts, observer, t0, t0 + 1/24)

    script = build_script(peaks_by_group, LOCATION_NAME)
    print(script)
    audio_path = save_briefing(script)
    logger.info("Briefing saved to %s (%d characters, backend=%s)", audio_path, len(script), TTS_BACKEND)