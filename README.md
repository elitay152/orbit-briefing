# orbit-briefing

![tests](https://github.com/elitay152/orbit-briefing/actions/workflows/tests.yml/badge.svg)

An end-to-end data project tracking satellite constellations (Amazon Leo and Starlink) from public
CelesTrak orbit data. A daily pipeline saves raw snapshots, validates them into a partitioned Parquet
lake, and DuckDB queries that lake to compute satellite passes, measure how quickly orbit predictions
go stale, and answer plain-English questions through a local LLM agent with sandboxed SQL tools.
Results are delivered as a short spoken briefing.

**Ask a question, get an answer, and see the SQL behind it:**

![The agent's chat UI answering which Amazon Leo launch has the most satellites, with the SQL and result shown](demo/agent_ui_answer.jpg)

**Ask it to delete data: the model tries, and the guardrail rejects it:**

![The agent's chat UI: asked to delete data, the model writes a DELETE and the guardrail rejects it](demo/agent_ui_guardrail.jpg)

**Highlights**
- Idempotent raw → Parquet pipeline, scheduled daily on GitHub Actions; history accumulates on the [`data` branch](https://github.com/elitay152/orbit-briefing/tree/data)
- Orbit-prediction error analysis that flags likely maneuvers (raising / lowering)
- Local agent (Ollama) with a chat UI that answers questions by writing SQL against a locked-down DuckDB sandbox
- [Evaluation set](#evaluation): fixes based on its failures took the agent from 73% to 91% on 22 scored questions
- Tested with pytest in CI, including guardrail tests for the agent's SQL tool

*Independent personal project using public data; not affiliated with Amazon, SpaceX or CelesTrak.*

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

## Ask the data: local LLM agent

The agent answers questions like *"Which Leo launch has the most satellites?"* using a local model
(Ollama). The system prompt describes the tables, columns, units and allowed values, and the model
has one tool: `run_sql(query)`, which runs a single read-only query and returns at most 50 rows.

The model never touches files or the real data directly. Guardrails are layered:
1. The lake is copied into an **in-memory** DuckDB, then **file access is disabled and the configuration locked**
2. Only a single `SELECT` / `WITH` statement is accepted, and results are row-capped
3. SQL errors are returned to the model as text so it can correct its own query

Each layer is covered by tests, including attempts to `DROP`, chain statements, read files, and
re-enable file access. Asked to delete the Starlink data during evaluation, the model really did try
`DELETE FROM orbital_elements`; the guardrail rejected it.

### Evaluation

22 questions with known answers are scored automatically. Correct answers come from gold SQL queries
run on the same data the agent sees, so they stay right as the data changes.

| Version (`qwen2.5:7b`) | Score | Number | Text | Should decline | Avg. time |
|---|---|---|---|---|---|
| Baseline | 16 / 22 (73%) | 12 / 14 | 2 / 4 | 2 / 4 | 23.7 s |
| Added a `launch` column, stricter prompt, schema in the prompt only | 20 / 22 (91%) | 14 / 14 | 3 / 4 | 3 / 4 | 15.5 s |

Still failing: a harder query comparing each satellite's first and latest records, and a question about
OneWeb, which isn't in the data (the agent answered with the Starlink count instead).

**Limits:** the fixes were made after seeing these same questions, so 91% is likely optimistic for new
questions. The set is small (one question is about 4.5 points), and scoring is simple: a number question
passes if the right number appears anywhere in the answer.

## Run
All commands run from the repository root.

```bash
python -m venv .orbit-venv
.orbit-venv\Scripts\activate        # macOS/Linux: source .orbit-venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # then edit LOCATION_NAME, LAT, LON, TIMEZONE

python -m orbit.pipeline.extract            # fetch raw snapshots from CelesTrak (cached for 2 hours)
python -m orbit.pipeline.load               # validate and write to the Parquet lake
python -m orbit.briefing                    # compute passes and generate the spoken briefing
python -m orbit.analysis.prediction_error   # prediction-error analysis + chart
```

**Agent** (requires [Ollama](https://ollama.com) and a tool-calling model):
```bash
ollama pull qwen2.5:7b       # or set OLLAMA_MODEL in .env
python -m streamlit run orbit/agent/app.py   # chat UI, showing the SQL behind each answer
python -m orbit.agent.agent                  # the same agent in the terminal
python -m orbit.agent.evaluate               # score the agent; saves a CSV to data/analysis/
```

## Tests
```bash
pytest
```

## Project structure
```
orbit-briefing/
├── orbit/                       # Python package
│   ├── config.py                # paths, settings, logging setup; reads .env
│   ├── briefing.py              # build the spoken script, save transcript + audio
│   ├── pipeline/
│   │   ├── extract.py           # fetch orbit data from CelesTrak, save raw snapshots (cached)
│   │   ├── load.py              # validate records, write Parquet snapshots (idempotent)
│   │   └── transform.py         # newest orbit per satellite, compute passes with skyfield
│   ├── analysis/
│   │   └── prediction_error.py  # propagate older records, measure error, classify maneuvers, chart
│   └── agent/
│       ├── agent.py             # local LLM agent: sandboxed DuckDB + SQL tool
│       ├── app.py               # Streamlit chat UI
│       ├── eval_cases.py        # evaluation questions with gold SQL queries
│       └── evaluate.py          # score the agent on those questions
├── tests/                       # pytest: validation, Parquet writes, speech helpers, prediction error, agent guardrails, eval scoring
├── demo/                        # sample briefing (audio + transcript) and charts
├── data/                        # generated, git-ignored
│   ├── raw/                     #   timestamped JSON snapshots per constellation
│   ├── lake/                    #   orbital_elements/… and run_metrics/… (constellation=…/snapshot=….parquet)
│   ├── briefings/               #   transcripts + audio from each run
│   └── analysis/                #   flagged-maneuver and evaluation CSVs
├── .github/workflows/           # tests.yml (CI on every push/PR), daily.yml (scheduled snapshot → data branch)
├── .env.example                 # settings: location, time zone, TTS backend, Ollama model
├── pytest.ini
└── requirements.txt
```

## Status
- [x] Extract → validate → partitioned Parquet lake (idempotent, cached)
- [x] Pass prediction over a location (skyfield) and spoken briefing in local time
- [x] Tests in CI; scheduled daily snapshots building history
- [x] Prediction-error analysis with maneuver classification
- [x] Package layout (`orbit/` with pipeline / analysis / agent modules)
- [x] Daily data-quality metrics per constellation (building history for SPC)
- [x] Local LLM agent with sandboxed SQL, a chat UI, and an evaluation set (scored questions with known answers)
- [ ] SPC control charts (I-MR on counts, p-chart on rejection rate) once ~25 days of metrics exist
- [ ] Held-out evaluation questions
- [ ] Altitude-by-launch analysis and dashboard
- [ ] Maneuver/decay detection over longer history