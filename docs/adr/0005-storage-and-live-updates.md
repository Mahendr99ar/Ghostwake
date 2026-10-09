# 5. SQLite locally, Postgres in production, an event table for live updates

**Status:** accepted

## Context

The project has to run on a laptop with no setup and on free hosting. The UI should show new alerts and other analysts' reviews without a reload.

## Decision

- SQLAlchemy models that work on both SQLite and Postgres. Times stored as UTC and normalised on read, because SQLite drops the timezone.
- Positions and detections are replaced on each run; alerts are merged by stable id so analyst status survives reruns.
- Every created or reviewed alert writes a row to `events`. The `/api/stream` endpoint polls that table every 3 seconds and pushes new rows as server-sent events.

## Consequences

- No message broker to host. One process, one database.
- Polling adds up to 3 seconds of delay, fine for this use.
- PostGIS is not required. Spatial work happens in Python on small data. At real scale the zone and distance checks should move into PostGIS with spatial indexes, and positions into time-partitioned tables.
