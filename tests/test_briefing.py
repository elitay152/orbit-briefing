import pytest
from briefing import compass, spoken_name

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