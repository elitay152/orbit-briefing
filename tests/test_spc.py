import duckdb
import pytest

from orbit.analysis.spc import (
    ALTITUDE_CHANGE_SQL, SNAPSHOT_METRICS_SQL, altitude_change_metrics, find_signals,
    individuals_limits, laney_limits, rate_signals, snapshot_metrics,
)
from orbit.config import LAKE_GLOB
from orbit.pipeline.load import to_dataframe, write_parquet


def test_laney_limits_match_hand_calculation():
    # p_bar = 150 / 2000 = 0.075; sigma = sqrt(0.075 * 0.925 / 1000) = 0.008329
    # z = -3.0017, 3.0017; moving range 6.0034; sigma_z = 6.0034 / 1.128 = 5.3222
    limits = laney_limits([50, 100], [1000, 1000])
    assert limits["p_bar"] == pytest.approx(0.075)
    assert limits["sigma_z"] == pytest.approx(5.322, abs=0.01)
    assert limits["ucl"][0] == pytest.approx(0.075 + 3 * 5.322 * 0.008329, abs=0.001)


def test_laney_sigma_z_is_never_below_one():
    # identical rates have no variation, so the limits fall back to a standard p-chart
    limits = laney_limits([50, 50, 50], [1000, 1000, 1000])
    assert limits["sigma_z"] == 1.0
    assert limits["ucl"][0] == pytest.approx(0.05 + 3 * (0.05 * 0.95 / 1000) ** 0.5)


def test_laney_lower_limit_stops_at_zero():
    assert laney_limits([1, 1], [100, 100])["lcl"] == [0.0, 0.0]


def test_laney_limits_need_at_least_two_points():
    with pytest.raises(ValueError):
        laney_limits([5], [100])


def test_large_samples_widen_limits_compared_with_a_standard_p_chart():
    # ordinary day-to-day variation shouldn't be flagged just because n is large
    changed = [600, 700, 650, 720, 610, 690]
    limits = laney_limits(changed, [11000] * 6)
    standard_width = 3 * (limits["p_bar"] * (1 - limits["p_bar"]) / 11000) ** 0.5
    assert limits["sigma_z"] > 1
    assert limits["ucl"][0] - limits["p_bar"] > standard_width
    assert not any(rate_signals(limits))


def test_rate_outside_limits_is_a_signal():
    limits = {"rates": [0.05, 0.20, 0.01], "ucl": [0.10] * 3, "lcl": [0.02] * 3}
    assert rate_signals(limits) == [False, True, True]


def test_altitude_change_counts_use_one_snapshot_per_day(valid_record, tmp_path, monkeypatch):
    monkeypatch.setattr("orbit.pipeline.load.LAKE_DIR", tmp_path)
    glob = (tmp_path / "*" / "*.parquet").as_posix()
    monkeypatch.setattr("orbit.analysis.spc.ALTITUDE_CHANGE_SQL",
                        ALTITUDE_CHANGE_SQL.replace(LAKE_GLOB, glob))
    other = dict(valid_record, NORAD_CAT_ID=63721)

    snapshots = [
        ("20261025T120000Z", [valid_record, other]),
        # same day as the next snapshot, so it's skipped: only the later one counts
        ("20261026T060000Z", [dict(valid_record, MEAN_MOTION=15.5), other]),
        # about 21 km higher for the first satellite, unchanged for the second
        ("20261026T120000Z", [dict(valid_record, MEAN_MOTION=14.97), other]),
    ]
    with duckdb.connect() as con:
        for snapshot, records in snapshots:
            df = to_dataframe(records, "kuiper", f"{snapshot}.json")
            write_parquet(con, df, "kuiper", snapshot)
        rows = altitude_change_metrics(con)

    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["compared"] == 2
    assert row["changed"] == 1
    assert row["raised"] == 1
    assert row["lowered"] == 0


def test_individuals_limits_match_hand_calculation():
    # mean 12; moving ranges 2, 2, 2 → average 2
    limits = individuals_limits([10, 12, 14, 12])
    assert limits["center"] == pytest.approx(12)
    assert limits["mr_bar"] == pytest.approx(2)


def test_limits_are_center_plus_or_minus_2_66_mr_bar():
    limits = individuals_limits([10, 14, 10, 14])       # mean 12, average moving range 4
    assert limits["center"] == pytest.approx(12)
    assert limits["ucl"] == pytest.approx(12 + 2.66 * 4)
    assert limits["lcl"] == pytest.approx(12 - 2.66 * 4)


def test_limits_need_at_least_two_values():
    with pytest.raises(ValueError):
        individuals_limits([10])


def test_stable_process_has_no_signals():
    values = [10, 11, 9, 10, 11, 9, 10]
    assert not any(find_signals(values, individuals_limits(values)))


def test_point_outside_limits_is_a_signal():
    limits = {"center": 10, "ucl": 13, "lcl": 7}
    assert find_signals([10, 14, 10, 6], limits) == [False, True, False, True]


def test_eight_in_a_row_on_one_side_is_a_signal():
    limits = {"center": 10, "ucl": 20, "lcl": 0}
    values = [11] * 8
    assert find_signals(values, limits) == [False] * 7 + [True]


def test_seven_in_a_row_is_not_a_signal():
    limits = {"center": 10, "ucl": 20, "lcl": 0}
    assert not any(find_signals([11] * 7 + [9], limits))


def test_snapshot_metrics_age_is_measured_in_utc(valid_record, tmp_path, monkeypatch):
    # the record's epoch is 08:14:22 UTC, so noon UTC is about 3.76 hours later,
    # whatever time zone the machine is in
    monkeypatch.setattr("orbit.pipeline.load.LAKE_DIR", tmp_path)
    glob = (tmp_path / "*" / "*.parquet").as_posix()
    monkeypatch.setattr("orbit.analysis.spc.SNAPSHOT_METRICS_SQL",
                        SNAPSHOT_METRICS_SQL.replace(LAKE_GLOB, glob))

    with duckdb.connect() as con:
        con.execute("SET TimeZone = 'America/Los_Angeles'")
        df = to_dataframe([valid_record], "kuiper", "20261025T120000Z.json")
        write_parquet(con, df, "kuiper", "20261025T120000Z")
        row = snapshot_metrics(con).iloc[0]

    assert row["constellation"] == "kuiper"
    assert row["satellites"] == 1
    assert row["median_age_hours"] == pytest.approx(3.76, abs=0.01)


def test_laney_limits_handle_no_changes_at_all():
    # a constellation where no satellite changed altitude must not crash the build
    limits = laney_limits([0, 0, 0], [391, 391, 391])
    assert limits["p_bar"] == 0
    assert limits["ucl"] == [0, 0, 0]
    assert not any(rate_signals(limits))
