# tidepool

A session loop that keeps long conversations inside the context window.

## Folding

The loop counts tokens on every turn. When the context crosses the threshold,
older turns are folded into a summary and the session continues on the summary.

## Handoff

When a new session takes over, only the summary is handed over; the raw turns
are dropped.
