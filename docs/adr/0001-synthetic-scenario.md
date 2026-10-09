# 1. Build on a synthetic scenario with planted ground truth

**Status:** accepted

## Context

There is no free AIS feed for Indian waters. Public archives (NOAA Marine Cadastre) cover US waters. Global Fishing Watch's API is free for non-commercial use, but it returns events, not raw positions, and the point of this project is to build the pipeline that produces such events.

## Decision

Generate a 36-hour scenario in the real geography (Gulf of Mannar, Palk Bay, the west coast near Kollam). Make it messy the way real feeds are messy. Plant five behaviours and record them as ground truth. Same seed, same data.

## Consequences

- Tests can measure recall and false alarms against known truth, not compare snapshots.
- Every number in the README is honest about what it measures: logic on planted events, not field performance.
- Thresholds are tuned to the scenario and will need retuning on real data.
- Swapping in a real feed means writing one ingest module; everything after cleaning is unchanged.
