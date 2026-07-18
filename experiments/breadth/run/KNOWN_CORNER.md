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

### Current Layer: auth3-floor-20260718

**Authoring batch 3 floored — the floor ate BOTH discriminator-shaped knots.**
`t3_null_filter_001` (felt-contradiction: three-valued NOT/!= over UNKNOWN) and
`t3_accrual_crossover_001` (derived-quantity: integer floor-compounding stall/
crossover): each settled **3/3 at the haiku floor on first flooring, hidden
vectors 10/10 every trial**. Solvers were fresh haiku subagents, bare framing
(no free-adapt), hidden graders stripped from working copies and prompts at
prep. Every grade run by the driver via `selfrun/grade.py`; all six hidden
graders re-run by hand verbatim (outputs sealed); `build_vectors.py --check`
re-confirmed discrimination (reference passes all, every paired naive fails a
knot vector) — so the passes are real, not grader rot. **Evidence
(hash-bound): `run/auth3_floor_20260718/MANIFEST.json`** — six candidate
sha256s, six verbatim grader outputs + hashes, graded ledger. Cost: $0
real-billed (shadow subagent tokens only).

**Finding:** these two tasks were purpose-built on the ONLY two measured
discriminator shapes (LESSONS 11b) to the batch-2 post-review standard — and
the floor ate them anyway. The solved-band membership therefore still rests on
a single point (`almanac_rule_boundary_001`, haiku 1/3 → fable-low), plus the
unsolved ceiling point (P8). Authored knots — even felt-contradiction and
derived-quantity shaped — keep settling; the only cells that have ever
separated models arose from *found* boundaries, not authored ones. The
capture program should bias toward found/OSS-derived boundary cells and
parametric intensity sweeps around the almanac point.

### Previous Layer: authoring2-floor-20260713

**Authoring batch 2 floored — the floor ate all three embedded knots.**
`t3_billing_anchor_001`, `t3_window_limit_001`, `t3_due_date_shift_001`: each
settled 3/3 (haiku, hidden vectors 9/9 · 10/10 · 10/10 per trial), every grade
re-run directly by the driver. **Evidence (hash-bound):
`run/authoring2_floor_20260713/MANIFEST.json`** — nine distinct preserved
candidates (sha256 ×9), each bound 1:1 to a distinct solver-subagent transcript
(transcript sha256 ×9; per-provider session IDs were not captured at dispatch,
the transcript hash is the identity retained), plus verbatim grader outputs and
their hashes. After the PR #84 review hardened the graders to enforce declared
return types, all nine candidates were **re-graded: 9/9 survives**. The knots
provably exist — each paired naive passes the visible checks and fails the knot
vectors — but haiku-as-spec-reader does not drift where a careless implementer
does. **Rule 11 corollary sealed into LESSONS.md:** embedded-unannounced is
necessary but not sufficient; the knots that actually bite are the ones whose
edge *feels contradictory* to the rule text (task02) or whose deciding quantity
must be *derived*, not applied (almanac lichun). Cost: $0 real-billed.

### Previous Layer: fanout-floor-20260713

**THE CORNER IS FULLY MAPPED — every breadth-valid task now settled.** The
operator's fan-out ran six parallel haiku solvers over the only two non-settled
cells (sediment diffed first; nothing settled was re-derived):

- **`t2_ossrf_fnmatch_charclass` settled 3/3 on its FIRST flooring** — the
  ARC-D admission task (CPython fnmatch character-class grammar, the task02
  escape-class knot in shipping code) is cheap-floor commodity. The task02
  residue was the boundary *commitment*, not the grammar.
- **`task08_select_exchange` settled 3/3** (lifetime 7/8) — three distinct
  driver-verified counterexamples, all nailing the greedy-blocks-completion
  flaw. The old 4/5 was a procedural bounds slip; an explicit bounds reminder
  (FREE adapt: prompt wording) and it never recurred. Rule 3 held: more cheap
  trials, never escalation on noise.

Cost: $0 real-billed (shadow subagent tokens only). Every grade run by the
driver against the hidden grader. Remaining non-settled rows are only the
characterized non-frontier artifacts: replay02 (spoiled-by-authoring),
replay04 (scaffold boot-load depth limit).

### Previous Layer: rule-boundary-escalation-fable-low-20260713

**THE ALMANAC RESIDUAL IS CLEARED — a second measured model-separation.** The one
cell that bit the cheap floor, `almanac_rule_boundary_001` (haiku **1/3**, the
lichun solar-longitude boundary), was walked up the effort ladder from the
cheapest rung above the floor and **cleared 3/3 at `claude-fable-5@low`** —
hidden 14/14 on every trial, including the Feb-3/4/5 2020 lichun year-boundary
vectors and the timezone→UT conversion pair the visible checks never touch.
Three genuinely independent derivations (distinct hashes; diffs 25/171/178
lines). This joins `task02_wildcard` (haiku 3/5 → sonnet@low 3/3) as the second
measured model×capability separation in the corner. **Effort-before-access held
exactly as designed:** the *lowest* Fable rung cleared it — no effort step-up, no
access escalation, no Opus solve. Driver (Opus) planned/delegated/graded only;
hands (fable@low) solved; every grade re-run by the driver against the hidden
oracle. Cost: unbilled shadow (keyless Agent-tool subagents). Receipts:
`run/ledger.jsonl` (3 `escalate` rows), sediment line in `known_corner.jsonl`.

### Previous Layer: crossing-event-task02-20260710

**THE CROSSING EVENT — capability transferred as an artifact, not a bigger
model.** The $0.68 captured rule commitment (task02's in-class-backslash
boundary), carried as an `emit_scaffold.py` packet, moves the haiku floor from
**unstable 3/5 (bare)** to **settled 5/5 (with packet)** — 10681/10681 on the
hidden oracle, every grade re-run by the driver, all five trials. Receipt +
candidates: `run/replays/task02_wildcard/`. Counted as **1 validated replay**
in the capture ledger (five trials of one instance = one reuse); the capture is
now `amortizing`, 1 of a projected 4 replays to break even — the remaining 3
must be distinct task02-class work items (ARC-B supplies them). Caveat: the
bare baseline's prompt wording (Jul 8) is not byte-identical; the designed
difference is the scaffold block only, and a same-session A/B is the named
next sharpening.

### Previous Layer: k3-floor-authored-tasks-20260710

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
- **crossing-event-task02-20260710**: the replay protocol's first run —
  haiku + the captured scaffold packet settles task02 5/5 where bare haiku
  was 3/5; the capture ledger records its first validated replay
  (amortizing, 1 of 4).
- **k3-floor-almanac-20260710**: first model results on the ARC-B almanac
  knot corpus (haiku K=3, hidden-graded, shadow-cost): exception_class and
  record_binding settled 3/3; **rule_boundary unstable 1/3** — every miss is
  the lichun solar-longitude boundary while all visible checks pass, the
  first almanac knot to bite (task02-shape judgment residue). Not a wall
  (1/3); Fable never turned on. Cross-engine note: exception_class agrees
  with the Codex lineage's independent floor (PR #63 draft, 3/3=3/3);
  record_binding: no disagreement (corrected — Codex's '1/3' was collection
  progress, 1 pass of 1 run; consistent with 3/3 here). Raw candidates +
  hidden-grader receipts exported hash-bound to
  `run/almanac_floor_20260710/` (correction1 layer).

- **replays2-4-and-ab-20260710**: CLAUDE-2/3 sealed. A/B closes the crossing
  event's wording confound (bare 3/5 vs packet 4/5, zero knot misses with the
  packet). Of the three attempted new work items, only replay03 VALIDATED;
  replay02 was spoiled by authoring and earned zero credit (capture ledger now
  amortizing 2 of 4); replay04 PARTIAL — the knot regressed through the packet
  at aggregate-count depth, the first measured limit of scaffold transfer.
- **rule-boundary-escalation-fable-low-20260713**: the ARC-B almanac residual
  (`almanac_rule_boundary_001`, haiku 1/3) escalated. `fable@low` clears it 3/3
  (hidden 14/14 x3, independent derivations) — second measured model-separation,
  effort-before-access held (lowest Fable rung, no access spend). The corner now
  has **no open frontier residual**: the haiku-floor `rule_boundary` unstable cell
  is superseded by the `@fable-low` settled cell; the only remaining `unstable`
  entries are `task08_select_exchange` (4/5 procedural, cheap-trial territory) and
  `replay04_count_matches` (a characterized scaffold-transfer limit) — neither a
  frontier wall.
