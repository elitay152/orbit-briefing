import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from briefing import compass, spoken_name, spoken_time

LA = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")

@pytest.mark.parametrize("name, expected", [
                         ("TESTNAME", "TESTNAME"), # no dash > unchanged
                         ("STARLINK-X1", "STARLINK-X1"), # non-numeric > unchanged
                         ("KUIPER-00028", "Kuiper 28"),
                         ("STARLINK-1007", "Starlink 1007"),
])
def test_spoken_name(name, expected):
    assert spoken_name(name) == expected

@pytest.mark.parametrize("azimuth, expected", [
    (0, "north"),
    (90, "east"),
    (221, "southwest"),
    (350, "north"),   # wraps around past 337.5°
    (359, "north"),
])
def test_compass(azimuth, expected):
    assert compass(azimuth) == expected

@pytest.mark.parametrize("utc_time, tz, expected", [
    (datetime(2026, 10, 27, 19, 42, tzinfo=timezone.utc), LA, "12:42 PM PDT"),  # daylight time
    (datetime(2026, 12, 15, 19, 42, tzinfo=timezone.utc), LA, "11:42 AM PST"),  # standard time
    (datetime(2026, 10, 27, 19, 42, tzinfo=timezone.utc), UTC, "7:42 PM UTC"),  # default: no conversion
])
def test_spoken_time_converts_to_local(utc_time, tz, expected):
    assert spoken_time(utc_time, tz) == expected