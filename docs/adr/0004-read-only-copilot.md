# 4. The copilot is read-only and its numbers are checked

**Status:** accepted

## Context

A language model in an enforcement tool can do damage two ways: by taking an action nobody approved, and by stating a figure that is not in the data. Vessel names and other fields are free text that a hostile actor controls, so tool results can carry injected instructions.

## Decision

- Four tools, all read-only. No SQL, no writes. Escalating and dismissing stay in the UI with a required note.
- Requests to act are refused before any model call.
- Tool results go back to the model inside `<data>` tags, with a system rule to treat them as data.
- Every number and date in the answer must appear in a tool result, the question, or a value the code computed. Anything else is listed and the UI shows a warning.
- A deterministic offline writer answers when no model is configured or the model fails, and it is the baseline for evals.

## Consequences

- The copilot can explain but never decide.
- The number checker misses a wrong number that happens to appear elsewhere in the results. It catches invented figures, not misattributed ones.
- A configured model has to beat the offline writer on `evals/run_evals.py` to earn its place.
