import duckdb
import pytest

import orbit.agent.agent as agent
from orbit.pipeline.load import to_dataframe, write_parquet

@pytest.fixture
def sandbox(valid_record, tmp_path, monkeypatch):
    lake = tmp_path / "lake"
    monkeypatch.setattr("orbit.pipeline.load.LAKE_DIR", lake)
    monkeypatch.setattr("orbit.agent.agent.LAKE_GLOB", (lake / "*" / "*.parquet").as_posix())

    with duckdb.connect() as writer:
        df = to_dataframe([valid_record], "kuiper", "test.json")
        write_parquet(writer, df, "kuiper", "20261028T000000Z")

    con = agent.open_sandbox()
    monkeypatch.setattr("orbit.agent.agent._con", con)
    yield con
    con.close()

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