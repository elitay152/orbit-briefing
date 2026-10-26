# orbit-briefing

A small data pipeline that tracks satellite constellations (Amazon Leo, Starlink)
using public orbit data from CelesTrak, and will generate a spoken pass briefing
with ElevenLabs.

## Status
- [x] Extract: fetch orbit data, save timestamped raw snapshots, skip if cache is fresh
- [x] Validate + load into DuckDB (idempotent)
- [ ] Compute passes over a location (skyfield)
- [ ] Spoken briefing (ElevenLabs)

## Run
python -m venv .orbit-venv
pip install -r requirements.txt
python extract.py