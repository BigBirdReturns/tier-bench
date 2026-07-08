# Known Corner Cases Analysis

> **Honesty caveat on the `initial` layer.** This layer was produced at **K=1** (one
> solve per task), which is **below the "settled" bar** (3/3 at `clear_thresh=1.0`).
> Read these three as "cleared once, independently re-verified" — not reliably settled.
> The grades ARE real: the hidden graders were re-run by hand off-workflow (task01
> 38/38, task02 10681/10681, task06 a genuine counterexample: subject `None` vs
> reference 2198). One nuance: `task06` cleared because the solver was prompted to
> *"return a counterexample"* (search-shaped), not to *judge correctness* — the
> framing did some of the lifting, which is the harness move, not raw derivation.
> To promote these to true `settled`, re-run at K=3. See `LESSONS.md`.

## Summary

This document tracks the classification of tasks across the breadth test suite as they accumulate through layers.

### Current Layer: k3-floor-20260708

**Settled Cells: 4** (K=3, hidden grades re-run by the driver)
- task01_parse_duration (3/3, hidden 38/38)
- task06_select (3/3, verified counterexamples — search-shaped framing caveat stands)
- t3_parse_duration_004 (3/3, tasks/ manifest via hidden_files mechanism)
- t4_plan_decomposition_001 (3/3, incl. hidden semantic judge)

These tasks are settled (cleared by the cheap hidden-graded floor → sealed-and-forget, commoditized). All three were resolved without requiring escalation to a stronger model.

**Unstable Cells: 1**
- task02_wildcard — 3/5 at the haiku floor. Both failures are the SAME edge:
  escape-inside-character-class, judged malformed (ValueError) where the oracle
  says non-matching (False). Not a wall (never 0/K), so escalation is
  unjustified; this is the first measured *reliability* residue at the floor,
  and it is a judgment edge, not a spec-coverage edge.

**Open Cells: 0**

No tasks currently classified as open (still a wall → the frontier residue). All probed tasks have been resolved.

## Re-run Protocol

**CRITICAL:** When performing a re-run:

1. **DIFF against the newest layer** — Compare the current run results against the most recent layer in known_corner.jsonl
2. **Only re-probe non-settled cells** — Skip any cells already marked as "settled" in prior layers
3. **Accumulate, never rewrite** — Append new layers to the corpus; old sediment is never re-derived

This accumulation strategy prevents unnecessary re-work and tracks the frontier of unresolved cases.

## Layer History

- **initial**: 3 settled tasks at K=1 (provisional — below the settled bar)
- **k3-floor-20260708**: initial layer re-probed at K=3 (K=5 where unstable) and
  promoted: task01/task06 settled; task02 demoted to unstable (3/5, single
  repeating judgment edge); the two hidden-graded tasks/ manifests sealed
  settled. Fable was never turned on — no wall appeared (LESSONS rule 2).

