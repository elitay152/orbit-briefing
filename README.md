# orbit-briefing

A small end-to-end data pipeline that tracks satellite constellations (Amazon Leo and Starlink)
using public orbit data from CelesTrak. It saves timestamped raw snapshots, validates and loads
them into DuckDB, computes which satellites pass over a location in the next hour, and turns the
results into a short spoken briefing (offline text-to-speech, with a pluggable engine).

## Sample output
A sample briefing generated for Seattle on 28 October 2026:
🔊 [Audio](demo/sample_briefing.wav) · 📄 [Transcript](demo/sample_briefing.txt)

## Status
- [x] Extract: fetch orbit data, save timestamped raw snapshots, skip if cache is fresh
- [x] Validate + load into DuckDB (logged rejections, idempotent inserts)
- [x] Compute passes over a location (skyfield, newest orbit per satellite)
- [x] Spoken briefing: script + transcript + audio via pluggable TTS (offline `pyttsx3` default)
- [ ] Local time zone in the briefing
- [ ] Scheduling (run the pipeline automatically)
- [ ] Tests for validation and speech formatting helpers

## Project structure

```
orbit-briefing/
├── config.py          # paths, settings, logging setup; reads .env
├── extract.py         # fetch orbit data from CelesTrak, save raw snapshots (cached)
├── load.py            # validate records, load into DuckDB (idempotent)
├── transform.py       # newest orbit per satellite, compute passes with skyfield
├── briefing.py        # build the spoken script, save transcript + audio
├── demo/              # sample briefing (audio + transcript)
├── data/              # generated, git-ignored
│   ├── raw/           #   timestamped JSON snapshots per constellation
│   ├── orbit.duckdb   #   orbital_elements table
│   └── briefings/     #   transcripts + audio from each run
├── .env.example       # required settings (location, TTS backend)
└── requirements.txt
```

## Run
python -m venv .orbit-venv
pip install -r requirements.txt
python briefing.py