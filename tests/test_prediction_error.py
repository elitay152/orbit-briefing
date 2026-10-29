import pytest
from datetime import datetime, timedelta, timezone
from skyfield.api import load

from orbit.analysis.prediction_error import altitude_km, classify, prediction_errors

def test_altitude_geostationary():
    assert altitude_km(1.00273791) == pytest.approx(35786, abs=5)

def test_higher_mean_motion_means_lower_orbit():
    assert altitude_km(15.5) < altitude_km(15.0)

@pytest.mark.parametrize("flagged, altitude_change, expected", [
    (False, 10.0, "normal"),    # not flagged -> normal
    (True, 3.0, "raising"),
    (True, -3.0, "lowering"),
    (True, 0.1, "small/unclear"),
    (True, 0.5, "small/unclear"),   # exactly at the threshold
])

def test_classify(flagged, altitude_change, expected):
    row = {"flagged": flagged, "altitude_change_km": altitude_change}
    assert classify(row) == expected

@pytest.fixture
def ts():
    return load.timescale()

def make_record(norad_id, epoch, mean_motion=15.04):
    return {
        "norad_cat_id": norad_id, "object_name": f"TEST-{norad_id}", "object_id": "2025-088A",
        "epoch": epoch, "mean_motion": mean_motion, "eccentricity": 0.0001,
        "inclination": 51.9, "ra_of_asc_node": 120.5, "arg_of_pericenter": 90.1,
        "mean_anomaly": 270.0, "bstar": 0.0001, "mean_motion_dot": 0.0,
        "mean_motion_ddot": 0.0, "classification_type": "U", "ephemeris_type": 0,
        "element_set_no": 999, "rev_at_epoch": 1234,
    }

def test_single_record_gives_no_pairs(ts):
    epoch = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    records = [make_record(1, epoch)]

    assert prediction_errors(records, ts, "test") == []

def test_pairs_stay_within_each_satellite(ts):
    t0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    records = [
        make_record(1, t0),
        make_record(1, t0 + timedelta(hours=12)),
        make_record(1, t0 + timedelta(hours=24)),
        make_record(2, t0),
    ]

    errors = prediction_errors(records, ts, "test")

    assert len(errors) == 2
    assert all(e["norad_cat_id"] == 1 for e in errors)

def test_identical_records_give_zero_error(ts):
    epoch = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    records = [
            make_record(1, epoch),
            make_record(1, epoch),
        ]

    errors = prediction_errors(records, ts, "test")

    assert len(errors) == 1
    assert errors[0]["error_km"] == pytest.approx(0, abs=1e-6)
    assert errors[0]["altitude_change_km"] == pytest.approx(0, abs=1e-6)
    assert errors[0]["age_days"] == 0