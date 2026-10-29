# orbit-briefing

![tests](https://github.com/elitay152/orbit-briefing/actions/workflows/tests.yml/badge.svg)

A small end-to-end data pipeline that tracks satellite constellations (Amazon Leo and Starlink)
using public orbit data from CelesTrak. It saves timestamped raw snapshots, validates them into a
partitioned Parquet lake queried with DuckDB, computes which satellites pass over a location in the
next hour, and turns the results into a short spoken briefing (offline text-to-speech, with a
pluggable engine).

## Sample output
A sample briefing generated for Seattle on 28 October 2026:
🔊 [Audio](demo/sample_briefing.wav) · 📄 [Transcript](demo/sample_briefing.txt)

## Prediction error: how fast do orbit predictions go stale?

![Prediction error vs. age](demo/prediction_error.png)

For each satellite, every older orbit record is propagated (SGP4) to the epoch of the next
record and compared with that record's position.

- **Typical error is ~7–10 km** for records up to a day apart, similar for Amazon Leo and Starlink,
  and grows with age (Starlink median: 6.7 → 9.7 → 12.6 km at ~0, 1, 2 days).
- **The tail is long:** mean error is 2–4× the median, driven by satellites that maneuvered.
  Altitude changes of only 10–27 km produced position errors of thousands of kilometers, because
  a small change in orbital period accumulates as along-track drift.
- **Flagging** pairs above 10× their age-bucket median and labeling by altitude change finds
  337 raising / 175 lowering maneuvers in Starlink and 5 / 6 in Amazon Leo over the first few days of data.
- Vertical bands in the Starlink cloud reflect the **batch cadence** of orbit-data updates.

*Based on a few days of snapshots; the daily job keeps extending the history.*

## Status
- [x] Extract: fetch orbit data, save timestamped raw snapshots, skip if cache is fresh
- [x] Validate + write a partitioned Parquet lake (logged rejections, idempotent writes)
- [x] Compute passes over a location (DuckDB over Parquet, skyfield)
- [x] Spoken briefing: script + transcript + audio via pluggable TTS (offline `pyttsx3` default)
- [x] Tests (pytest) running in CI on GitHub Actions
- [x] Scheduled daily runs
- [x] Local time zone in the briefing
- [x] Add orbit prediction error

## Run
```bash
python -m venv .orbit-venv
.orbit-venv\Scripts\activate        # macOS/Linux: source .orbit-venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # then edit LOCATION_NAME, LAT, LON

python extract.py     # fetch raw snapshots from CelesTrak
python load.py        # validate and write to the Parquet lake
python briefing.py    # compute passes and generate the briefing
```

## Tests
```bash
pytest
```

## Project structure
```
orbit-briefing/
├── config.py          # paths, settings, logging setup; reads .env
├── extract.py         # fetch orbit data from CelesTrak, save raw snapshots (cached)
├── load.py            # validate records, write Parquet snapshots (idempotent)
├── transform.py       # newest orbit per satellite, compute passes with skyfield
├── briefing.py        # build the spoken script, save transcript + audio
├── tests/             # pytest tests (validation, Parquet writes, speech helpers)
├── demo/              # sample briefing (audio + transcript)
├── data/              # generated, git-ignored
│   ├── raw/           #   timestamped JSON snapshots per constellation
│   ├── lake/          #   orbital_elements/constellation=…/snapshot=….parquet
│   └── briefings/     #   transcripts + audio from each run
├── .github/workflows/ # CI: runs pytest on every push and pull request
├── .env.example       # required settings (location, TTS backend)
├── pytest.ini
└── requirements.txt
```