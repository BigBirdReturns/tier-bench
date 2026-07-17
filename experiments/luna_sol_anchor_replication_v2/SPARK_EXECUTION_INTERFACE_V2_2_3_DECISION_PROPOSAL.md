# Spark Execution Interface v2.2.3 Decision Proposal

Date: 2026-07-16

Current disposition: **PROPOSAL ONLY — NO RETRY OR BENCHMARK AUTHORIZED**

## Exact decision required

Authorize or reject a prospective v2.2.3 administrative protocol that keeps
the frozen task, grader, schedule, models, budgets, hidden vectors, planner
semantics, paired comparison repair, and path boundaries, but changes the Spark
execution interface to the empirically successful planner-handoff design:

1. Keep the planner's structured output and controller validation.
2. Render each accepted crate into a concise normal-text execution handoff with
   objective, allowed paths, forbidden paths, dependencies, stop condition, and
   the exact executable visible-validator command.
3. Invoke Spark free-form on the app-inherited writable CLI surface, without a
   Spark output schema and without `--ignore-user-config`.
4. Require Spark to run the visible validator before finishing.
5. Ignore Spark's final prose for candidate admission. The controller admits
   only the actual allowed-path Git diff plus a passing validator and writes the
   structured hand receipt itself.

This would be a new versioned protocol. It would not retry, rewrite, or admit
the failed v2.2.2 canary.

## Evidence

`SPARK_FREEFORM_EXECUTION_PROBE_20260716.md` records:

- 0/9 when the effective writable app configuration was stripped;
- 2/3 for a minimal free-form prompt on the app-inherited surface;
- 3/3 with raw-byte self-verification;
- 3/3 with an executable local validator;
- 3/3 for a planner-authored one-file Python implementation handoff with an
  executable validator.

## Affected files if authorized

- `experiments/luna_sol_anchor_replication_v2/run_v2.py`
- a new versioned v2.2.3 administrative-canary script;
- the Spark base prompt or a new v2.2.3 handoff renderer;
- controller-contract fixtures and a new additive gate receipt;
- a new CLI/dispatch freeze receipt binding the app-inherited command vector;
- `docs/agents/QUEUE.md` as a new claimed v2.2.3 row before implementation.

No v2.2.2 or earlier raw output, receipt, comparison, report, prompt, schema, or
run directory would be edited.

## Proposed minimal implementation

1. Split `invoke` into structured planner invocation and free-form Spark
   execution invocation.
2. Preserve the existing CLI path/hash/version binding and writable sandbox.
3. Do not pass `--output-schema` for Spark execution calls.
4. Include the exact controller-approved visible-validator command in the
   rendered handoff.
5. After Spark exits, mechanically compute changed paths and run the validator
   again under the controller interpreter.
6. Admit only an allowed-path diff with a passing controller rerun; otherwise
   retain the existing typed rejection classes.
7. Synthesize the hand receipt from controller observations rather than Spark
   claims.

## Regression tests

- Stripping app-inherited configuration is detected as an administrative
  surface failure before a measured call.
- Spark execution command contains no output-schema argument.
- Planner calls remain schema-bound and unchanged.
- Exact validator command appears in the Spark handoff.
- Passing allowed-path edit is admitted even when final prose is absent or
  malformed.
- Claimed success with a failing validator is rejected.
- Out-of-crate edits are rejected even when the validator passes.
- No diff is rejected.
- Validator, task, or forbidden-file mutation is rejected.
- Controller-authored receipt binds prompt, crate, parent state, patch, final
  state, validator output, CLI identity, and command vector.
- Existing paired-comparison and incomplete-collection gates remain green.

## Rerun gates

1. Claim a new v2.2.3 queue row after explicit authorization.
2. Implement and pass all deterministic controller, custody, task-consistency,
   strict-schema, and comparison tests.
3. Run free-form synthetic execution canaries only; stop on any failure.
4. Commit canary evidence and bind the exact commit before any benchmark
   authorization is considered.
5. Benchmark execution remains a separate explicit decision.

## Evidence preservation

- Preserve all five versioned partial attempts and both v2.2.2 administrative
  block sequences.
- Preserve all 21 free-form probe calls and their raw events.
- Do not reinterpret exploratory success as benchmark evidence.
- Use new output directories and versioned receipts only.
