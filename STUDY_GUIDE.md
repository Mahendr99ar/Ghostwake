# Studying GhostWake after you deploy it

This guide walks the code in the order the data flows, so each file builds on the one before it. Budget about three weeks at two hours a day. Each step has something to read, something to break on purpose, and questions you should be able to answer out loud without looking.

An interviewer will pick one line and ask why it is there. The goal of this guide is that you can always answer.

## Week 1: data in, behaviour out

### Day 1. Run it and watch it

- Run the pipeline and the API locally. Open `http://localhost:8000/docs` and call every endpoint by hand.
- Open the web app. Click every alert. Play the timeline.
- Read `README.md` and `docs/adr/` in full.

You should be able to say: what GhostWake does in two sentences, who the two kinds of users are (enforcement analyst, fishing crew), and what is simulated.

### Day 2. The scenario: `ingest/synthetic.py`

Read `Path`, `Vessel` and `_fleet()`. Every planted behaviour is a few lines here.

Break it: change SEA FALCON's `ais_off=[(8.0, 19.0)]` to `[(8.0, 11.0)]`. Run `pytest`. Which tests fail, and why does a 3-hour gap not raise an alert?

Answer out loud:
- Why is the data messy on purpose?
- What does `truth` hold, and why do tests use it instead of comparing to a saved output?
- What is the AIS cadence of a cargo ship here versus a fishing boat, and why do they differ?

### Day 3. Cleaning: `ingest/ais.py`

Learn: regex for MMSI, mixed timestamp parsing, the 0,0 "null island" problem, why sorting matters before `diff()`.

Break it: remove the `drop_duplicates` line. Which rule starts behaving oddly? (Hint: implied speed between two identical timestamps.)

Answer out loud:
- Why count dropped rows by reason instead of just dropping them?
- What would break if timestamps stayed as strings?

### Day 4. Geometry: `geo.py` and `zones.py`

Learn: haversine distance, bearing, point-in-polygon by ray casting, distance from a point to a polyline, which side of a line a point is on. Draw each on paper.

Break it: in `zones.py`, swap two points of the IMBL. Which test catches it?

Answer out loud:
- Why is a local flat projection fine for distances under ~100 km?
- How does the IMBL rule decide a boat "crossed" rather than "came close"?
- Why are the boundaries marked "approx." everywhere, including the UI?

### Day 5. Rules: `anomalies/rules.py`

One function per behaviour. Read them in this order: `ais_gaps`, `spoofing`, `ban_period_fishing`, `imbl`, `rendezvous`, `loitering_in_protected`.

Learn: pandas `groupby`, `diff`, resampling tracks onto a regular clock (`_resample`), finding the longest run of `True` values.

Break it: set `rendezvous_hours` to 0.5 in `config.py`. Count the new alerts. Are they real?

Answer out loud:
- Why is the IMBL rule limited to fishing boats?
- Why do harbour fixes get excluded from three different rules?
- What is the false-positive risk of each rule? Which one worries you most?

### Day 6 and 7. Tests: `tests/test_rules.py`, `tests/test_ingest.py`

Read every test. Notice the two kinds: tests on the planted scenario (recall on known truth) and tests that inject one event into a clean track.

Exercise: write a new test that injects a 2-hour meeting between two cargo ships and asserts it is found. Then make it pass without changing the rule.

## Week 2: radar, fusion, scoring, API

### Day 8. Radar detection: `detect/sar.py`

Learn: what speckle is, why sea clutter is modelled as gamma or exponential power, how CA-CFAR estimates local clutter from a ring of training cells, and why the guard band must be wider than half a ship.

Break it: set `guard=2`. Run `test_cfar_finds_planted_ships_and_little_else`. Explain the failure using the word "self-masking".

Answer out loud:
- What does `pfa` control, and what happens at 1e-3 versus 1e-8?
- Why is CFAR the baseline any ML model must beat?

### Day 9. The ML model: `detect/train_yolo.py`

You can't run this locally. Read it, then run it on Kaggle with 4 to 6 xView3 scenes.

Learn: tiling large images, YOLO label format (class, centre x, centre y, width, height, all 0 to 1), why the xView3 challenge scored by point distance (200 m) and not box overlap, why empty tiles are kept at 5%.

When you have a real F1 number, put it in the README next to the CFAR number. That one table is worth more in an interview than any feature.

### Day 10. Fusion: `fusion/match.py`

The heart of the project. Learn: interpolating a ship's position at the radar's exact time, dead reckoning when only one nearby fix exists, the cost matrix, `linear_sum_assignment` (Hungarian algorithm), the gate that grows with time since the last fix.

Break it: replace the Hungarian step with "for each detection, take the nearest ship". Run the fusion tests. Find the scene where two ships are close and see the wrong match.

Answer out loud:
- Why one-to-one assignment instead of nearest neighbour?
- How is a dark blip linked to a silent ship, and why is that only "possible identity"?
- What would a Kalman filter add to `_guess_identity`?

### Day 11. Scoring: `risk.py`

Learn: additive explainable scoring, combining independent evidence with `1 - prod(1 - s)`, why linked alerts on one ship add weight.

Exercise: an analyst says the ban-fishing score (20) is too low compared to a 40 m dark vessel far from anything (40). Argue both sides. Then write down what data you would need to stop guessing weights (answer: reviewed alerts as labels, then a small model with SHAP to keep the "reason, points" output).

### Day 12. Storage and the pipeline: `db.py`, `pipeline.py`

Learn: SQLAlchemy 2 models, why alert ids are hashes (idempotency), why reviews are append-only, why positions are replaced but alerts are merged, what the `events` table is for.

Break it: make alert ids random (`uuid4`). Run the pipeline twice. Count alerts. Run `test_rerunning_pipeline_keeps_analyst_decisions`.

### Day 13. API: `api/main.py`

Learn: FastAPI dependencies (`db`, `require_analyst`), Pydantic request models, why dismiss needs a note, the in-memory rate limiter and its weakness (it resets on restart and is per process), server-sent events and why the stream sends a keep-alive comment.

Answer out loud:
- Why `secrets.compare_digest` and not `==`?
- What happens to the SSE stream when Render puts the service to sleep?
- How would you replace the shared token with real accounts?

### Day 14. Copilot: `copilot/tools.py`, `copilot/agent.py`, `evals/`

Learn: tool calling, why the copilot has four read-only tools and no SQL, the three guardrails (action refusal, data wrapped in `<data>` tags, number verification), the offline writer as fallback and reference.

Exercise: add an eval case that should fail today. Make it pass. Run `evals/run_evals.py`.

Answer out loud:
- What is prompt injection here, concretely? (A vessel name is attacker-controlled text.)
- How does the number checker handle "11.07" being said as "11.1"? What can it still miss?

## Week 3: frontend, deployment, and making it yours

### Day 15 and 16. Frontend: `web/src`

Read in order: `lib/api.ts`, `lib/vocab.ts`, `lib/tracks.ts`, `App.tsx`, `components/Queue.tsx`, `components/CasePanel.tsx`, `components/MapView.tsx`, `components/Timeline.tsx`.

Learn: TanStack Query caching and invalidation after a review, MapLibre style sources and layers, deck.gl `TripsLayer` with a moving `currentTime`, why `positionAt` returns `null` inside long gaps, the reduced-motion check, keyboard shortcuts.

Exercise: add a sixth legend entry and map mark for "Meeting at sea" that draws a line between the two ships at the playhead.

### Day 17. Deployment

Read `render.yaml`, `docker-compose.yml`, both workflows, and `DEPLOY.md` again now that you have done it. Run `docker compose up --build` once.

Answer out loud:
- Why does the start command run the pipeline before the server?
- What is baked into the frontend at build time, and what is read at runtime?
- What fails first if 1,000 people open the site at once? (Render free CPU, then the per-process rate limiter, then Neon connections.)

### Day 18 to 21. Make it yours

Pick one and finish it properly, with tests and a line in the README:

1. **Real AIS.** NOAA's Marine Cadastre publishes free US AIS archives. Write `ingest/noaa.py`, point the pipeline at one day of a busy US port, and see which rules survive real data.
2. **Real radar.** Train the YOLO model on Kaggle and report F1 next to CFAR.
3. **Kalman filter** for the silent-track guess, with currents from Open-Meteo.
4. **Learned scores.** Escalate and dismiss 50 alerts yourself, train LightGBM on those labels, show SHAP reasons in the ledger.
5. **Palantir Foundry mirror.** On the free Developer Tier, build the same Ontology (Vessel, Track, Detection, Alert, Case), load the pipeline output, and build a Workshop view. Screenshot it for the README.

## Questions to rehearse

Practise each answer in under a minute.

1. Walk me through what happens from a raw AIS row to an alert on screen.
2. Your system flags a ship as dark. How sure are you, and how would you make it more sure?
3. Why did you build rules first instead of an ML model?
4. How do you know the rules work? What is your recall, on what data, and what is the catch?
5. A fisheries officer says there are too many alerts. What do you change first?
6. Tell me about a bug you found while building this. (Have a real one ready. Two that happened while building this: CFAR missing long ships because the guard band was too narrow, and the copilot's number checker flagging "07" from a timestamp as a made-up figure. Both fixes have a comment in the code explaining them.)
7. What would you need to run this for the Indian Coast Guard? (Real data licences, accounts and audit, on-premise or Indian-region hosting, official boundary data, a small-boat detection plan.)
8. What are the ethical risks, and what did you do about them?
9. Why is the copilot read-only?
10. If you had another month, what would you build?
