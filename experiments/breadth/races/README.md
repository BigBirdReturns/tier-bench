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
