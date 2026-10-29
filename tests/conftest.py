import pytest

@pytest.fixture
def valid_record():
    return {
        "OBJECT_NAME": "KUIPER-00028",
        "OBJECT_ID": "2025-088A",
        "NORAD_CAT_ID": 63720,
        "EPOCH": "2026-10-25T08:14:22.123456",
        "MEAN_MOTION": 15.04,
        "ECCENTRICITY": 0.0001,
        "INCLINATION": 51.9,
        "RA_OF_ASC_NODE": 120.5,
        "ARG_OF_PERICENTER": 90.1,
        "MEAN_ANOMALY": 270.0,
        "BSTAR": 0.0001,
        "MEAN_MOTION_DOT": 0.00001,
        "MEAN_MOTION_DDOT": 0.0,
        "CLASSIFICATION_TYPE": "U",
        "EPHEMERIS_TYPE": 0,
        "ELEMENT_SET_NO": 999,
        "REV_AT_EPOCH": 1234,
    }