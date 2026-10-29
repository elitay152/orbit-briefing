import duckdb
import pytest

from orbit.pipeline.load import validate_record, to_dataframe, write_parquet

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
    yield connection
    connection.close()

def test_write_parquet_is_idempotent(con, valid_record, tmp_path, monkeypatch):
    monkeypatch.setattr("orbit.pipeline.load.LAKE_DIR", tmp_path)
    df = to_dataframe([valid_record], "kuiper", "test.json")

    first = write_parquet(con, df, "kuiper", "20261028T000000Z")
    second = write_parquet(con, df, "kuiper", "20261028T000000Z")

    assert first == second                               # same snapshot → same file
    assert len(list(tmp_path.rglob("*.parquet"))) == 1   # overwritten, not duplicated
    
    rows = con.execute(f"SELECT norad_cat_id FROM read_parquet('{first.as_posix()}')").fetchall()
    assert rows == [(63720,)]