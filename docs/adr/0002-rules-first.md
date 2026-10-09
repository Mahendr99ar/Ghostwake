# 2. Rules and fusion first, learned scoring later

**Status:** accepted

## Context

Supervised anomaly models need labels: which alerts were worth an analyst's time. There are none on day one. Analysts also need to know why something was flagged before they act on it.

## Decision

Each behaviour is a small, separately tested rule. Scores are additive, with a named reason for every point. Analyst decisions are stored, append-only, with a note.

## Consequences

- Every alert is explainable on day one.
- Weights are judgement calls (see ADR 3).
- Reviews accumulate into a labelled set. The planned upgrade is a gradient-boosted model whose SHAP values feed the same "reason, points" ledger, so the interface does not change.
