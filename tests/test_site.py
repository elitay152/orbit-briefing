from datetime import datetime, timezone
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from orbit.pipeline.load import to_dataframe, write_parquet
from orbit.site.build import compute_kpis, load_evaluation

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- KPI calculations ----------------------------------------------------------

@pytest.fixture
def points():
    return pd.DataFrame({
        "constellation": ["kuiper", "kuiper", "starlink", "starlink", "starlink", "starlink"],
        "changed": [True, False, True, True, False, False],
    })


@pytest.fixture
def frames():
    # day-old pairs: held altitude errors 4, 6 (median 5); changed 40, 60 (median 50)
    return {"kuiper": pd.DataFrame({
        "age_days": [1.0, 1.0, 1.0, 1.0, 3.0],
        "altitude_change_km": [0.1, -0.2, 3.0, -5.0, 9.0],
        "error_km": [4.0, 6.0, 40.0, 60.0, 9999.0],   # the 3-day-old pair is outside the window
    })}


@pytest.fixture
def metrics():
    times = pd.to_datetime(["2026-10-28T12:00", "2026-10-29T12:00", "2026-10-30T12:00"])
    return pd.DataFrame({
        "constellation": ["kuiper"] * 3 + ["starlink"] * 3,
        "snapshot_time": list(times) * 2,
        "median_age_hours": [20.0, 22.0, 24.0, 18.0, 19.0, 20.0],
    })


def test_kpis(points, frames, metrics):
    positions_at = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    kpis = compute_kpis(points, frames, metrics, positions_at)

    assert kpis["satellites"] == 6
    assert kpis["counts"] == {"kuiper": 2, "starlink": 4}
    assert kpis["changed"] == 3
    assert kpis["changed_share"] == {"kuiper": 0.5, "starlink": 0.5}
    assert kpis["held_km"] == 5
    assert kpis["changed_km"] == 50
    assert kpis["ratio"] == pytest.approx(10)
    assert kpis["snapshots"] == 3
    assert kpis["date_range"] == "Oct 28 – Oct 30, 2026"
    assert kpis["positions_at"] == positions_at


def test_kpis_without_prediction_pairs(points, metrics):
    kpis = compute_kpis(points, {}, metrics, datetime(2026, 10, 30, tzinfo=timezone.utc))
    assert kpis["ratio"] is None
    assert kpis["held_km"] is None


def test_load_evaluation_adds_the_latest_local_run(tmp_path):
    summary = tmp_path / "eval_summary.json"
    summary.write_text(json.dumps({"heldout": {"questions": 15}}), encoding="utf-8")
    pd.DataFrame({"correct": [True, False]}).to_csv(tmp_path / "eval_heldout_old.csv", index=False)
    pd.DataFrame({"correct": [True, True, False]}).to_csv(tmp_path / "eval_heldout_z_new.csv", index=False)

    evaluation = load_evaluation(summary, tmp_path)

    assert evaluation["latest_run"] == {"correct": 2, "questions": 3, "file": "eval_heldout_z_new.csv"}


def test_load_evaluation_without_a_summary(tmp_path):
    assert load_evaluation(tmp_path / "missing.json", tmp_path) is None


# --- full build on a tiny lake -------------------------------------------------

SNAPSHOTS = ["20261025T120000Z", "20261026T120000Z", "20261027T120000Z"]


@pytest.fixture
def tiny_lake(valid_record, tmp_path, monkeypatch):
    """Two satellites per constellation over three daily snapshots; one of each changes altitude."""
    lake = tmp_path / "lake"
    monkeypatch.setattr("orbit.pipeline.load.LAKE_DIR", lake)

    with duckdb.connect() as con:
        for day, snapshot in enumerate(SNAPSHOTS):
            epoch = f"2026-10-{25 + day}T08:00:00.000000"
            for constellation, base_id in (("kuiper", 70000), ("starlink", 80000)):
                records = [
                    dict(valid_record, NORAD_CAT_ID=base_id, EPOCH=epoch,
                         OBJECT_NAME=f"{constellation.upper()}-1", MEAN_MOTION=15.04),
                    dict(valid_record, NORAD_CAT_ID=base_id + 1, EPOCH=epoch,
                         OBJECT_NAME=f"{constellation.upper()}-2", MEAN_MOTION=15.04 + 0.02 * day),
                ]
                df = to_dataframe(records, constellation, f"{snapshot}.json")
                write_parquet(con, df, constellation, snapshot)
    return lake


def test_build_writes_the_page_and_every_image_it_references(tiny_lake, tmp_path):
    out = tmp_path / "site"
    env = dict(os.environ, LAKE_DIR=str(tiny_lake),
               LAT=os.environ.get("LAT", "47.6205"), LON=os.environ.get("LON", "-122.3493"),
               LOCATION_NAME=os.environ.get("LOCATION_NAME", "Seattle"), MPLBACKEND="Agg")

    result = subprocess.run([sys.executable, "-m", "orbit.site.build", "--out", str(out)],
                            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]

    page = (out / "index.html").read_text(encoding="utf-8")
    sources = re.findall(r'<img src="([^"]+)"', page)
    assert len(sources) >= 6
    for src in sources:
        assert (out / src).exists(), src

    visible_text = html.unescape(re.sub(r"<style.*?</style>|<[^>]+>", " ", page, flags=re.S))
    assert "not affiliated" in visible_text
    assert "Every satellite I'm tracking: 4," in visible_text   # counted from the fixture, not hardcoded
    assert not re.search(r"\bnan\b", visible_text, flags=re.I)  # no missing values leaking into the page


# --- wording that has to stay true as the history grows ------------------------

from orbit.site.build import limits_note, prediction_title, rate_comparison_title, signals_text


@pytest.mark.parametrize("ratio, expected", [
    (None, "How fast satellite orbit predictions go stale"),
    (7.9, "Satellites that change altitude are about 8× harder to predict"),
    (1.2, "Satellites that change altitude are about as predictable as those that don't"),
    (0.5, "Satellites that change altitude are, surprisingly, easier to predict"),
])
def test_prediction_title_fits_any_ratio(ratio, expected):
    assert prediction_title(ratio) == expected


@pytest.mark.parametrize("p_bars, expected", [
    ({"kuiper": 0.019, "starlink": 0.063}, "Starlink satellites change altitude about 3× as often as Amazon Leo's"),
    ({"kuiper": 0.09, "starlink": 0.03}, "Amazon Leo satellites change altitude about 3× as often as Starlink's"),
    ({"kuiper": 0.05, "starlink": 0.06}, "Amazon Leo and Starlink satellites change altitude at similar rates"),
    ({"kuiper": 0.0, "starlink": 0.06}, "Starlink satellites change altitude; Amazon Leo's almost never do"),
    ({"starlink": 0.06}, "How many satellites change altitude each day"),
])
def test_rate_comparison_title_follows_the_data(p_bars, expected):
    spc = {group: {"p_bar": p, "signals": 0, "points": 6} for group, p in p_bars.items()}
    assert rate_comparison_title(spc) == expected


@pytest.mark.parametrize("signals, expected", [
    (0, "No unusual days so far."),
    (1, "1 unusual day flagged; it's marked on the chart."),
    (3, "3 unusual days flagged; they're marked on the chart."),
])
def test_signals_text(signals, expected):
    assert signals_text(signals) == expected


def test_limits_note_stops_saying_preliminary_with_enough_history():
    assert limits_note(6, "daily comparisons").startswith("Preliminary: 6 daily comparisons so far")
    assert limits_note(400, "snapshots") == "Limits are calculated from all 400 snapshots."
