import duckdb
import pytest

from load import create_table, load_records, validate_record, to_dataframe, write_parquet

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

def test_valid_record_has_no_issues(valid_record):
    assert validate_record(valid_record) == []

@pytest.mark.parametrize("field, bad_value", [
    ("MEAN_MOTION", -1),          # not positive
    ("MEAN_MOTION", "fast"),      # not a number
    ("EPOCH", "garbage"),         # not a timestamp
    ("NORAD_CAT_ID", None),       # present but empty
])
def test_invalid_field_is_reported(valid_record, field, bad_value):
    record = dict(valid_record, **{field: bad_value})
    issues = validate_record(record)
    assert any(field in issue for issue in issues)

def test_missing_field_is_reported(valid_record):
    record = dict(valid_record)
    del record["NORAD_CAT_ID"]
    assert any("NORAD_CAT_ID" in issue for issue in validate_record(record))

@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    create_table(connection)
    yield connection
    connection.close()

def test_load_is_idempotent(con, valid_record):
    df = to_dataframe([valid_record], "kuiper", "test.json")
    first = load_records(con, df)
    second = load_records(con, df)
    count = con.execute("SELECT count(*) FROM orbital_elements").fetchone()[0]

    assert first == 1
    assert second == 0
    assert count == 1

def test_write_parquet_is_idempotent(con, valid_record, tmp_path, monkeypatch):
    monkeypatch.setattr("load.LAKE_DIR", tmp_path)
    df = to_dataframe([valid_record], "kuiper", "test.json")

    first = write_parquet(con, df, "kuiper", "20261028T000000Z")
    second = write_parquet(con, df, "kuiper", "20261028T000000Z")

    assert first == second                               # same snapshot → same file
    assert len(list(tmp_path.rglob("*.parquet"))) == 1   # overwritten, not duplicated