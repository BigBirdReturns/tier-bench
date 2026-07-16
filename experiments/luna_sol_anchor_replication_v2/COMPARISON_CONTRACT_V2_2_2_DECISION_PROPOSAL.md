# Luna/Sol Anchor Replication v2.2.2 Comparison-Contract Decision Proposal

Date: 2026-07-16

Current disposition: **DETERMINISTIC_GATE_BLOCK_PREREGISTRATION_COMPARISON_MISMATCH**

The frozen preregistration says the anchor signal is present when the correct-anchor arm "passes more paired replicates and at least two of three favor it." The current implementation first filters both arm lists to passing rows and then counts a pair only when the already-filtered no-anchor row is not a pass. That second condition is unreachable.

Smallest three-pair witness:

- correct-anchor hidden outcomes: pass, pass, pass
- no-anchor hidden outcomes: fail, fail, fail
- preregistered result: `ANCHOR_CAUSAL_SIGNAL_ON_FROZEN_TASK`
- current implementation result: `NO_ANCHOR_MECHANISM_IDENTIFIED`

This is a deterministic contract contradiction, not a capability result. No prior partial is reinterpreted. Comparison rules are gated, so the implementation has not been changed.

## Exact decision required

Authorize or reject a prospective v2.2.2 repair that makes the completed-run implementation match the already-frozen preregistration by pairing correct-anchor and no-anchor outcomes by replicate before filtering/counting passes.

## Affected files

- `experiments/luna_sol_anchor_replication_v2/run_v2.py`
- `experiments/luna_sol_anchor_replication_v2/scripts/controller_contract_gate.py`
- prospective v2.2.2 controller-contract receipt
- `docs/agents/QUEUE.md`

The preregistration, completed v2.2.1 comparisons/reports, task, validator, grader, schedule, models, budgets, prompts, schemas, and hidden vectors would remain unchanged.

## Proposed minimal diff

Replace only the anchor-mechanism expression with a replicate-keyed comparison over the complete table:

1. Index the three correct-anchor rows and three no-anchor rows by `trial`.
2. Count correct-anchor passes and no-anchor passes for the "passes more paired replicates" clause.
3. Count favored pairs where the correct-anchor outcome is `pass` and the same trial's no-anchor outcome is not `pass`.
4. Emit `ANCHOR_CAUSAL_SIGNAL_ON_FROZEN_TASK` only when correct-anchor passes are greater and at least two paired trials favor correct-anchor; otherwise emit `NO_ANCHOR_MECHANISM_IDENTIFIED`.

No label, threshold, comparison population, or stopping rule changes.

## Regression tests

- 3 correct-anchor passes versus 3 paired no-anchor failures emits the anchor signal.
- 2 correct-anchor passes versus 1 paired no-anchor pass with two favored pairs emits the anchor signal.
- Equal pass counts do not emit the anchor signal.
- Fewer than two favored pairs do not emit the anchor signal.
- Missing, duplicate, or incomplete rows remain `PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT` with null verdicts.
- The Sol-replication expression remains byte-for-byte logically unchanged.

## Rerun gates

1. Regenerate a prospective controller-contract receipt; every test, including the positive anchor witness, must pass.
2. Re-run the 11-test task/visible/hidden consistency gate and 12 strict schema tests.
3. Re-run the v2.2.1 custody/hash audit.
4. Resolve the separate CLI-surface decision.
5. Only then run the Spark schema preflight, Luna planner canary, Spark crate-scope canary, and fresh benchmark.

## Evidence preservation

- Preserve the original completed-run formula and outputs in Git history and all v2.2.1 evidence byte-for-byte.
- Preserve the earlier mechanically green v2.2.2 receipt as superseded evidence; do not overwrite it.
- Preserve the failing semantic-audit receipt additively.
- Do not award a benchmark or capability verdict from any deterministic witness.
