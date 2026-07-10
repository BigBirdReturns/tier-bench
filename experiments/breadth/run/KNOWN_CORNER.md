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

### Current Layer: k3-floor-authored-tasks-20260710

**Settled Cells: 2 new** (K=3, hidden grades re-run by the driver)
- task09_pattern_class (3/3, hidden 24/24 incl. all 7 inverted-range knot vectors)
- task10_topo_endmin (3/3, hidden 14/14; all three trials independently
  derived the backward smallest-sink construction)

**Unstable Cells: 1 new**
- task08_select_exchange — 4/5 at the haiku floor. The four passes span BOTH flaw
  classes the task was built around (greedy-suboptimality and the
  ≥2-displacement repair-insufficiency). The single miss found the right flaw
  class but returned a value outside the stated domain bound (51 > 50) — a
  PROCEDURAL constraint-compliance slip, not the reasoning knot. Not a wall
  (never 0/K), so escalation is unjustified.

**Headline finding of this layer:** all three tasks were purpose-built as
novel-reasoning discriminators (counterexample construction, a task02-isomorphic
rule-boundary knot, an anti-pattern-match derivation objective) — and the haiku
floor cleared or near-cleared every one at K=3/K=5 with trimmed packets. The
counterexample-construction hypothesis did NOT wall haiku (consistent with the
task06 search-shaped-framing result). Suspected defusal on task09: the spec
guarantee "you never need to reject a pattern" telegraphs the
malformed-vs-unsatisfiable resolution — see the authoring lesson in
`../LESSONS.md`. Fable was never turned on for solving; run cost was ~$0.52
shadow (subagent estimates), $0 real-billed.

### Cumulative state (all layers)

**Settled: 7** — task01_parse_duration, task06_select, t3_parse_duration_004,
t4_plan_decomposition_001, task02_wildcard (at sonnet-5@low — the one measured
model-separation), task09_pattern_class, task10_topo_endmin.

**Unstable: 1** — task08_select_exchange (4/5 at the haiku floor, procedural miss).

**Open (walls): 0**

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
- **model-ladder-task02-20260708**: the one unstable cell walked up the model
  ladder; task02 settled at sonnet-5@low 3/3 (real-billed ~$0.23/trial) — the
  first measured model-separation (H6 confirmed once).
- **k3-floor-authored-tasks-20260710**: the three newly authored tasks
  (task08/09/10) floored at K=3 (K=5 on task08): task09/task10 settled,
  task08 unstable 4/5 with a procedural (domain-bounds) miss. No wall; Fable
  never turned on for solving.

