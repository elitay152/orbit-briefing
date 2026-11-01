import duckdb
import pytest
import pandas as pd

from orbit.pipeline.load import validate_record, to_dataframe, write_parquet, build_metrics, write_metrics

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

def test_build_metrics_values(valid_record):
    df = to_dataframe([valid_record], "kuiper", "test.json")
    row = build_metrics("20261025T120000Z", 3, df, 2).iloc[0]

    assert row["records_fetched"] == 3
    assert row["records_valid"] == 1
    assert row["records_rejected"] == 2
    assert row["satellites"] == 1
    assert row["median_epoch_age_hours"] == pytest.approx(3.76, abs=0.01)

def test_build_metrics_all_rejected():
    row = build_metrics("20261025T120000Z", 5, None, 5).iloc[0]

    assert row["records_fetched"] == 5
    assert row["records_valid"] == 0
    assert row["records_rejected"] == 5
    assert row["satellites"] == 0
    assert pd.isna(row["median_epoch_age_hours"])     # no valid records, so no age


def test_write_metrics_is_idempotent(con, valid_record, tmp_path, monkeypatch):
    monkeypatch.setattr("orbit.pipeline.load.METRICS_DIR", tmp_path)
    df = to_dataframe([valid_record], "kuiper", "test.json")
    metrics = build_metrics("20261025T120000Z", 1, df, 0)

    first = write_metrics(con, metrics, "kuiper", "20261025T120000Z")
    second = write_metrics(con, metrics, "kuiper", "20261025T120000Z")

    assert first == second                               # same snapshot → same file
    assert len(list(tmp_path.rglob("*.parquet"))) == 1   # overwritten, not duplicated

    rows = con.execute(f"SELECT records_valid FROM read_parquet('{first.as_posix()}')").fetchall()
    assert rows == [(1,)]


def test_metrics_files_read_together_when_a_day_is_all_rejected(con, valid_record, tmp_path, monkeypatch):
    monkeypatch.setattr("orbit.pipeline.load.METRICS_DIR", tmp_path)
    df = to_dataframe([valid_record], "kuiper", "test.json")

    write_metrics(con, build_metrics("20261025T120000Z", 1, df, 0), "kuiper", "20261025T120000Z")
    write_metrics(con, build_metrics("20261026T120000Z", 5, None, 5), "kuiper", "20261026T120000Z")

    glob = (tmp_path / "*" / "*.parquet").as_posix()
    rows = con.execute(f"""
        SELECT snapshot, median_epoch_age_hours, typeof(median_epoch_age_hours)
        FROM read_parquet('{glob}', hive_partitioning = true)
        ORDER BY snapshot
    """).fetchall()

    assert rows[0][1] == pytest.approx(3.76, abs=0.01)   # normal day has an age
    assert rows[1][1] is None                            # all-rejected day is NULL
    assert rows[1][2] == "DOUBLE"                        # same column type on both days