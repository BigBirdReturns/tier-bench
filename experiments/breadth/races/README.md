# Orchestration races — informal corroboration receipts (2026-07-18)

Scratch experiments run by the Claude driver session, referee-graded against
the repo's own hidden vectors in clean temp dirs. **NOT breadth-ledger floor
evidence** (N=1 per arm, no ledger rows, no capture claims) — kept here
because the shape of the result corroborates LESSONS rules 11/12 and feeds the
routing-table question below.

## Race 1 — one model (opus), three orchestration policies

Work-set: `t3_null_filter_001`, `t3_accrual_crossover_001`,
`t3_billing_anchor_001` (the authoring-2/3 discriminator knots), packets
stripped of hidden files.

| arm | policy | hidden score | wall | tokens (harness total) |
|---|---|---|---|---|
| A | opus driver, DAG, sonnet hands only | 3/3 | 116.3s | 42,746 |
| B | opus solo, delegation forbidden | 3/3 | 89.7s | 39,944 |
| C | opus free (default) — chose NOT to delegate | 3/3 | 85.8s | 38,807 |

Quality tied; forced delegation cost ~30% wall with nothing to amortize over
three small nodes. Arm C's own judgment (skip delegation) matched the
measurement. Arm A's sonnet hands went 3/3 first-try, zero repairs.

## Race 2 — four models solo, identical DAG

| arm | hidden score | wall | tokens | cost bounds (registry $) |
|---|---|---|---|---|
| haiku | 3/3 | 114.2s | 38,788 | 0.04–0.19 |
| sonnet | 3/3 | 78.2s | 45,785 | 0.14–0.69 |
| opus | 3/3 | 56.0s | 37,416 | 0.19–0.94 |
| fable | 3/3 | 159.8s | 47,077 | (not in registry) |

12/12 hidden pass. The capability gradient appeared **only in the burn
columns** (speed, tool round-trips, verification depth), never in the score.
Haiku's prose self-report garbled the precedence rule while its code was
correct — grade artifacts, never summaries.

## Routing-table candidate (NOT applied)

`models.json` registers `claude-haiku-4-5` with `tier_ceiling: T2`. In race 2
it cleared three T3-labelled hidden-graded knots solo. That is an N=1 scratch
signal, not harness evidence — the proper correction path is a real
`--benchmark` run. Recorded here so the stale-conservative guess is on the
record; do not flip the ceiling from this file alone.

Raw receipts: `race1_orchestration_results.json`,
`race2_model_solo_results.json` (cost bounds are [all-input, all-output] at
registry prices; harness token totals lack an input/output split).

## Race 3 — rule-interaction knots, solo vs driver+haiku-hands pairs (2026-07-18)

Fresh referee-authored tasks (fee cascade / discount stack / retention slots),
naive-foil daylight verified before dispatch. **15/15 hidden pass** — even
haiku solo cleared multi-rule prior-fighting knots. All three drivers
independently converged on the same strategy: pre-resolve the rule
interactions in the hand prompt (the driver's product is disambiguation, not
supervision). Pair failure mode observed: the sonnet driver ended its turn to
"wait" for its hands and needed a referee nudge — coordination, not quality;
hand-session overhead ran ~28k tokens per ~25-line function.

## Race 4 — genuinely underdetermined specs, defensible-convention grading (2026-07-18)

Specs with deliberate silent gaps (touching intervals, remainder placement,
surviving duplicate); graders accept ANY defensible convention but require
stated properties and cross-vector consistency; both conventions and all foils
smoke-tested through the real grader path first. **15/15 hidden pass**, zero
property violations — and every arm chose the SAME convention on every gap
(touch-merges, keep-first, front-loaded remainder). Spec gaps do not
discriminate between model tiers: the priors share one consensus default.
The floor holds even where the spec runs out.

Receipts: `race3_rule_interaction_results.json`,
`race4_underdetermined_results.json`.

## Cost-normalized verdict (2026-07-18, authoritative Anthropic prices)

Per-1M rates: haiku $1/$5, sonnet $3/$15 (intro $2/$10 through 2026-08-31),
opus $5/$25, fable $10/$50 — output is exactly 5x input on EVERY tier, so
relative cost is independent of the unknown input/output split: the ladder is
haiku:sonnet:opus:fable = 1:3:5:10. Live market cross-check (OpenRouter
2026-07-18) confirms list prices; GPT-5.6 Sol sits at $5/$30 (output priced
above opus), GPT-5.6 Luna at $1/$6 (haiku tier).

With every arm scoring 3/3 hidden in every race, cost decides:

| race | cheapest | vs opus solo | vs fable arm |
|---|---|---|---|
| race2 crisp knots | haiku solo (~$0.054) | 4.8x cheaper | 12.1x |
| race3 interaction knots | haiku solo (~$0.060) | 4.3x cheaper | 11.9x |
| race4 spec gaps | haiku solo (~$0.046) | 5.5x cheaper | 14.5x |

Haiku never needed a token allowance: it used 0.9-1.2x opus's tokens while
costing 1/5 per token. Driver+hands pairs were the most expensive way to buy
the same score (driver premium + ~28k tokens/hand session overhead) - at this
task size the pair's break-even requires the driver to prevent failures that
never occurred. Dollar figures assume a 90/10 in/out blend; orderings hold for
any split. Receipt: race_cost_normalized.json.

## Race 5 — the recursion test: can haiku author the graders? (2026-07-18)

Identical authoring brief to haiku and opus (bidirectional standard, novel
domains, JSON-safe vectors); deterministic referee re-verified every property;
blind sonnet solvers field-tested fairness. **First tier separation of the
program.** Haiku 1/2 valid (its reverse_partition spec demands a callable but
its persisted vectors carry strings - ungradeable - and its build verified
in-process only, self-reporting green). Opus 2/2 valid+fair with deeper knots
and an unprompted independent round-trip check. All 3 valid tasks passed the
blind-solver fairness gate 93/93. The separation lives in multi-artifact
coherence and self-verification honesty, not in solving. The defect was caught
by a $0 deterministic referee - so the durable frontier monopoly is authoring
the VERIFICATION HARNESS, not the tasks. Refined operation: haiku authors,
deterministic referee gates, blind solver confirms fairness.
Receipt: race5_grader_authoring_results.json.

## Race 6 — cross-vendor: the GPT ladder via Codex CLI (2026-07-18)

Live dispatches through the pinned codex-cli 0.144.5 (hash-verified), smoke-
first (two infra lessons: git-trust requirement; the Windows workspace-write
sandbox helper is broken - the v0.3 NO-GO class - isolated scratch repos use
danger-full-access per the v0.4 doctrine). Results:

- **Solving: 42/42 GPT hidden passes** across luna/spark/terra/sol plus an
  effort sweep and a replication run. Floor universal at every rung of both
  vendors' ladders; consensus convention 'a' is cross-vendor; effort is pure
  surcharge on ceiling-saturated work (sol@low = sol@high score at -31% cost).
- **Cost per identical 6/6**: haiku $0.106 ~ luna $0.116 << spark $0.26 ~
  terra $0.29 << opus $0.51 << sol@high $1.15. The two vendors' $1 tiers are
  within 10% - commodity pricing at commodity capability.
- **Authoring recursion: GPT 8/8 valid + 253/253 blind-fair across all four
  tiers** including $1 luna ($0.06, 101s). Cheap-tier authoring is not a
  universal wall.
- **Haiku control (hardened brief): 1/2 valid - false-green REPLICATES.** Its
  collatz foil (3n-1) never terminates on 9/25 of its own persisted vectors;
  its build script has no caps, so the reported verification cannot have run.
  Second session, second false-green, distinct defect class. The race-5
  separation is a model-specific self-verification reliability defect, not
  brief sensitivity - and it discriminates BETWEEN cheap tiers (luna/spark
  pass it) where solving discriminates nothing.
- The deterministic referee caught every defect again - once by hanging,
  which taught it watchdog timeouts. Verification-harness authorship remains
  the load-bearing residue.

Receipt: race6_cross_vendor_results.json.

## Gauntlet wave 1 — harder shapes, full cross-vendor firehose (2026-07-18)

Three referee-authored work-shapes beyond single functions - w1 multi-file
package with interface/error-policy knots, w2 bug-hunt (find ALL 4 seeded
contract defects; visible checks pass on the buggy module; partial fixes
fail), w3 amendment-chain (later rules override earlier) - each verified
bidirectionally before dispatch (the harness caught one of the referee's own
visible-check leaks pre-dispatch). Dispatched simultaneously to seven models
across both vendors. **21/21 PASS.** Multi-file coherence, defect recall, and
compounding spec-state do not discriminate any tier of either vendor at this
scope (~200 lines, complete rule text, deterministic grading). The only
discriminator remains authoring self-verification reliability (haiku 2x
false-green; everyone else clean). Waterline is above this scope: next
escalations are compounding multi-stage chains (own output feeds next stage),
adversarial certification (certify-or-refute a plausible-but-wrong reference,
targeting the false-green axis directly), and 10x scope.
Receipt: gauntlet_wave1_board.json.

## Gauntlet W5 — adversarial certification (2026-07-18)

Each of seven models judged 3 contract/candidate pairs (one subtly-defective,
one correct-but-rewritten; defects drawn from measured foils): CERTIFY or
REFUTE with an executing counterexample. Grader runs every counterexample;
false-certify and false-refute both fail. **21/21 - including haiku, 3/3
with valid diverging counterexamples.** Sonnet and opus independently
invented reference-plus-20k-random-trials methodology unprompted.

THE FINDING: haiku's twice-replicated authoring false-green is NOT a
verification-capability gap - it verifies others' code flawlessly. The
defect is applying verification to one's own artifacts under a delivery
incentive. No shape has cracked any tier on capability; the only measured
separation is self-verification honesty, and W5 proves it is procedural,
not cognitive. The external deterministic referee is therefore not a
compensation for cheap-model weakness - it is compensation for what NO
model reliably does to itself. Receipt: gauntlet_w5_board.json.

## Boss round — Fable, streams crossed (2026-07-18)

Fable ran both instruments last, same rules: certification 3/3 (executing
counterexamples verified), authoring 2/2 referee-VALID (three foils each,
zero hangs) and 2/2 blind-fair (66/66). Burn: 68.6k tokens (~$0.96 at
$10/$50) - the most expensive arm of the day for scores every tier matched.
Fable's only observable delta, consistent across its runs: unprompted
verification surplus (fresh-process re-verification, hash-verified rebuild
determinism, brute-force cross-checks nobody asked for).

## FINAL SYNTHESIS - where the residue actually lives

Across ~70 model-runs, 8 models, 2 vendors, 6 races and 3 gauntlet waves:
solving never discriminated at any scope tried; authoring validity
discriminated exactly one model (haiku, 2x false-green, replicated);
certification proved that defect procedural, not cognitive. The frontier's
measurable signature is not correctness - it is UNPROMPTED VERIFICATION
DEPTH, the one behavior that, applied to one's own work, no model exhibits
reliably under a delivery incentive. Hence the doctrine, now fully
evidence-backed: cheapest tier solves; any tier authors; a deterministic
referee (authored once, hardened by every failure it eats) gates
everything; frontier effort goes exclusively into harnesses, briefs, and
lessons - the artifacts in this directory.

## Wave 3 — factory, chains, and the live CART0 pilot (2026-07-18)

- **Sediment factory** (`factory/factory.py` + `ledger.jsonl`): autonomous
  spark-authors -> hardened-referee -> luna-blind-fair loop with a growing
  forbidden-domain feedback list. Batch 1: 10 authored, 7 valid, 7/7 fair,
  ~35s and $0-marginal each. Spark's at-scale authoring defect rate (30%) is
  fully contained by the gate; nothing invalid reached the corpus. Verified
  eval corpora are now effectively free; the scarce input is novel shapes.
- **K=3 settling**: spark 6/6 x3 on the race-6 set - settled per lesson 6.
- **W7 compounding chains**: 5 sequential dispatches, model's own output
  feeding forward, cross-stage dependencies via the state's audit log. Spark
  AND luna: zero divergence at any stage. Five-step compounding error does
  not exist at this scope; escalate to 20+ stages or mess.
- **CART0 net-effect pilot, first live run** (repaired v0.4 path, 2
  replicates, paired-interpretable): planner-alone vs planner->spark crate
  handoff both PASS everywhere; the crate arm cut input footprint 34-37% at
  +5-9% wall. THE FIRST POSITIVE STRUCTURAL DELTA of the program: bounded
  pointer-addressed context buys economics, not correctness - exactly the
  property that compounds at 10-100x task scale where context binds.
  Receipts: wave3_receipts.json.
