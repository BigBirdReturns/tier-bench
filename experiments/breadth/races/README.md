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
