from datetime import datetime, timedelta, timezone
import math

import pytest
from skyfield.api import load

from orbit.analysis.satellite_map import changed_flags, snapshot_time, subpoint
from orbit.analysis.spc import ALTITUDE_CHANGE_KM
from orbit.pipeline.load import to_dataframe

EARTH_MU = 398600.4418
EARTH_RADIUS_KM = 6378.137


def mean_motion_for(altitude_km: float) -> float:
    """Orbits per day for a circular orbit at this altitude (the inverse of altitude_km)."""
    a = altitude_km + EARTH_RADIUS_KM
    return math.sqrt(EARTH_MU / a**3) * 86400 / (2 * math.pi)


def row(norad_id, altitude_km, constellation="kuiper"):
    return {"constellation": constellation, "norad_cat_id": norad_id,
            "mean_motion": mean_motion_for(altitude_km)}


@pytest.mark.parametrize("change_km, expected", [
    (0.0, False),
    (ALTITUDE_CHANGE_KM - 0.01, False),   # just under the threshold
    (ALTITUDE_CHANGE_KM + 0.01, True),    # just over
    (-(ALTITUDE_CHANGE_KM + 0.01), True), # lowering counts too
    (20.0, True),
])
def test_changed_flag_threshold(change_km, expected):
    previous = [row(1, 550.0)]
    latest = [row(1, 550.0 + change_km)]
    assert changed_flags(latest, previous) == [expected]


def test_satellite_missing_from_previous_snapshot_is_unchanged():
    previous = [row(1, 550.0)]
    latest = [row(1, 550.0), row(2, 400.0)]       # satellite 2 is new
    assert changed_flags(latest, previous) == [False, False]


def test_same_id_in_another_constellation_isnt_matched():
    previous = [row(1, 550.0, "starlink")]
    latest = [row(1, 600.0, "kuiper")]
    assert changed_flags(latest, previous) == [False]


def test_snapshot_time_is_the_newest_source_file():
    rows = [{"source_file": "20261102T155626Z.json"}, {"source_file": "20261103T141700Z.json"}]
    assert snapshot_time(rows) == datetime(2026, 11, 3, 14, 17, tzinfo=timezone.utc)


@pytest.mark.parametrize("hours_later", [0, 1, 6, 12, 24])
def test_subpoint_is_a_valid_latitude_and_longitude(valid_record, hours_later):
    record = to_dataframe([valid_record], "kuiper", "test.json").to_dict("records")[0]
    when = record["epoch"].to_pydatetime() + timedelta(hours=hours_later)

    lat, lon = subpoint(record, load.timescale(), when)

    assert -90 <= lat <= 90
    assert -180 <= lon <= 180
    assert abs(lat) <= valid_record["INCLINATION"] + 0.5   # can't go further from the equator than its tilt
