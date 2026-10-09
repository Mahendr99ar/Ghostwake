# GhostWake

Ships can switch off their tracker. They can't hide their wake.

GhostWake watches the Gulf of Mannar and its approaches, off the southern tip of India. It fuses satellite radar detections with AIS ship tracking to find vessels that went quiet, flags behaviour worth a second look (meetings at sea, position spoofing, fishing during the monsoon ban), and warns Indian fishing boats before they drift across the International Maritime Boundary Line into Sri Lankan waters. An analyst reviews every alert. The software never acts on its own.

![Case view of a dark vessel inside the marine park](docs/screenshots/dark-vessel-case.png)

## What it does

| Signal | How it is found | Who it is for |
| --- | --- | --- |
| Dark vessel | A radar detection that no AIS ship can explain, matched with the Hungarian algorithm | Enforcement |
| AIS switched off | A silence of 6 h or more away from harbour | Enforcement |
| Possible identity of a dark vessel | The blip sits on the straight line a silent ship would have followed | Enforcement |
| Position spoofing | Consecutive fixes that need more than 40 knots | Enforcement |
| Meeting at sea | Two ships within 0.5 km, both under 3 knots, for 2 h or more, outside any port | Enforcement |
| Fishing during the ban | Fishing-speed activity away from harbour inside the east or west coast ban window | Enforcement |
| Near or across the IMBL | An Indian fishing boat within 5 km of the boundary, or over it | Crew safety |

Every alert carries:

- a score built from named reasons ("AIS switched off +25, inside marine park +15"), never a bare number
- its lineage: pipeline run, rule, thresholds, source records, and what the cleaner removed on that run
- an append-only review history, so a dismissed alert keeps the note that explains why
- a printable case file

The copilot answers questions about alerts using four read-only tools. It refuses requests to act, and every number in its answer is checked against the tool results it used.

## What is real and what is simulated

Free AIS data for Indian waters does not exist, so the demo runs on a 36-hour synthetic scenario (20 to 21 May 2026) that is messy on purpose: duplicate rows, broken coordinates, three timestamp formats, MMSIs typed three ways. Five behaviours are planted in it and recorded as ground truth, which is what the tests check against. Radar detections are simulated the same way, with position and length error and sea clutter.

The detection model is real code but needs real data. `ghostwake/detect/train_yolo.py` trains a YOLO ship detector on the public xView3-SAR dataset on a free Kaggle or Colab GPU, and `ghostwake/detect/sar.py` holds the classic CA-CFAR detector it should beat. Boundaries and the marine park outline are hand-drawn approximations. They are not legal lines and must never be used for navigation.

## Results on the scenario

Measured by the test suite, seed 7:

| Check | Result |
| --- | --- |
| AIS rows cleaned | 5,114 in, 5,002 out (100 duplicates, 12 bad positions) |
| Planted behaviours found | 5 of 5 (gap, spoofing, meeting, ban fishing, IMBL crossing) |
| False alarms on boats tied up in harbour | 0 |
| Radar detections of AIS ships matched to the right ship | 34 of 34 |
| Dark ships raised as alerts | 10 of 10 radar sightings |
| Sea clutter raised as alerts | 0 of 6 |
| Silent ship linked to its radar blip | 1 of 1, and no wrong links |
| Warning lead time before the IMBL crossing | 53 minutes |
| Copilot eval cases passed (offline mode) | 13 of 13 |
| Backend tests | 29 passing |

These numbers are on simulated data built to contain these behaviours, so they show the logic works, not how it would do at sea. Real AIS and real Sentinel-1 scenes are the next step.

## Architecture

```
Public data            Processing                       Serving                  People
-----------            ----------                       -------                  ------
SAR imagery  ----->    batch: ship detection    -.
AIS tracks   ----->    stream: clean, rules     --+-->  fusion + risk  -->  FastAPI  -->  Analyst console
Zones, IMBL  ----->    (synthetic for the demo) -'      Postgres          copilot       Fishing-boat warnings
                                                        event log         MCP server
```

- **backend/** Python 3.12, FastAPI, SQLAlchemy 2, pandas, SciPy, H3. SQLite locally, Postgres (Neon) in production.
- **web/** React 18, TypeScript, Vite, MapLibre GL, deck.gl, TanStack Query.
- **Pipeline** runs on start and every morning through GitHub Actions. It is idempotent: alert ids are stable hashes, so a rerun updates evidence but never overwrites an analyst's decision.
- **Live updates** go to the browser over server-sent events.

Design decisions and their trade-offs are written up in [docs/adr](docs/adr).

## Run it locally

You need Python 3.11+ and Node 20+.

```bash
# API
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m ghostwake.pipeline            # builds ghostwake.db from the scenario
uvicorn ghostwake.api.main:app --reload # http://localhost:8000/docs

# Web, in a second terminal
cd web
npm install
npm run dev                             # http://localhost:5173
```

The default analyst token is `change-me`. Set `GW_ANALYST_TOKEN` before showing it to anyone.

Or run the whole stack with Postgres: `docker compose up --build`.

Tests:

```bash
cd backend && pytest -q && PYTHONPATH=. python evals/run_evals.py
cd web && npm test
```

Keyboard: `j` and `k` move through the queue, `Esc` closes a case, `Space` plays the replay.

The interface follows your device's light or dark setting. The Auto / Day / Night switch in the top bar overrides it for that browser. Day mode is styled after a printed nautical chart, night mode after a chart room with the lights down.

![Day theme](docs/screenshots/day-theme.png)

## Deploying

Free tiers only: Neon for Postgres, Render for the API, Vercel for the web app, GitHub Actions for the daily run. Step by step in [DEPLOY.md](DEPLOY.md).

## Project layout

```
backend/
  ghostwake/
    ingest/      synthetic scenario, AIS cleaning
    anomalies/   one function per behaviour rule
    fusion/      radar to AIS matching, dark-vessel identity
    detect/      CA-CFAR detector, YOLO training script, radar chips
    copilot/     read-only tools, LLM loop, offline writer, guardrails
    api/         HTTP API, live stream, case file
    risk.py      explainable scoring
    pipeline.py  one full run, idempotent
    mcp_server.py
  tests/  evals/
web/src/
  components/  MapView, Queue, CasePanel, Timeline, SarChip, Glyph
  lib/         API client, track interpolation, shared vocabulary
docs/adr/      decision records
```

## Limitations

- Simulated data. Thresholds are tuned to the scenario, and real traffic will need retuning.
- The dark-vessel identity guess uses a straight line between fixes. Currents and a Kalman filter would do better.
- Sentinel-1 misses boats much under 15 to 20 m, which is most of the Indian small-boat fleet. The IMBL warning relies on AIS, which many of those boats do not carry.
- The analyst token is a shared secret. A real deployment needs per-user accounts.
- Scores are hand-weighted. Once there are enough analyst decisions, they should become training labels.

## Responsible use

Public and synthetic data only. No imagery or analysis of military installations. Vessels and patterns, never individuals. The copilot is read-only and every escalation is a human decision with a written reason. Global Fishing Watch data, if you add it, is free for non-commercial use only and needs attribution.
