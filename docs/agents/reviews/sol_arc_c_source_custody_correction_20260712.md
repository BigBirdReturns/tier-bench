# ARC-C source-custody correction — 2026-07-12

Disposition: prior nine-observation Codex floor seal superseded; partial run
retained with one source-admissible 3/3 cell.

## Trigger

PR #63 review found that `scripts/validate_orchestration_run.py` compared each
declared manifest hash to the current checkout rather than to
`pairing.source_commit`. The run declared
`e416462fdf36c711faf06717212d8de19cd07216`, whose almanac manifest bytes do not
match the recorded hashes.

## Adjudication

Commit `3d3837165ac9e046acf2cecc27e01f9c41c302e5` is the first commit containing
the exact recorded manifest bytes. It was authored at `2026-07-10T16:09:20Z`.
Thread identities establish these execution times:

- the three exception-class observations and record-binding trial 1 began
  between `2026-07-10T15:16:15Z` and `15:17:58Z`, before the exact source commit;
- record-binding trials 2 and 3 ran after the commit, but their preserved broker
  routes counted excluded trial 1 and therefore are not independent admissible
  continuations;
- all three rule-boundary observations ran after the commit and their broker
  routes depend only on source-admissible rule-boundary predecessors.

The first six observations remain byte-preserved and receive explicit exclusion
receipts. They count as neither trials nor broker evidence. The active run is
rebound to `3d383716…`, retains rule-boundary trials 1–3, becomes `partial`, and
sets `measurement_claim: false`.

## Failure default

No exception-class or record-binding capability, route, cost, or cross-engine
claim may be drawn from this administration. Fresh source-bound observations are
required. No model was rerun to produce this correction.
