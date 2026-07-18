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
