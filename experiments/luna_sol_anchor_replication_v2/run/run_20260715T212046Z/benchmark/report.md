# Luna/Sol Anchor Replication v2.1

protocol_revision: `2.1`
task_version: `derived_ledger_rollup_v2`
new_run: `run_20260715T212046Z/benchmark`
prior_partial_run: `run_20260715T205630Z`
suite_commit_used: `46b27eb6dc838e0a3875f341a00dbe97a0262e22`
schema_repair_commit: `bf5161a367f2ddd8f86dad1b9b4ee2656167d08b`
support_commits: `b2111dfdb8d631915305fadddc6624d7e8c9f600`, `46b27eb6dc838e0a3875f341a00dbe97a0262e22`

## Administrative preflight

The exact three-schema `$ref` union was accepted by the pinned user-space CLI in one unscored Spark-low read-only call. Exit code was `0`; the returned object passed the repository-owned ordinary instance validator and the recursive strict gate. Usage: `input_tokens=11915`, `output_tokens=691`, `reasoning_output_tokens=637`, `cached_input_tokens=0`.

## Schema identities

| Schema | Old SHA-256 | New SHA-256 | Repair |
|---|---|---|---|
| `full_agent.schema.json` | `fa179ee41a6ef43fc2269894c7eb2d3e2b3dc5b31dd0fca569355f7080ab306e` | `6b1925ef255c2c5dd5bf0b4e44c18e06c2765d7a91eabb1cc2579935cf075b8e` | required `detail`, nullable `detail` |
| `planner.schema.json` | `521bdb435fc8108de26aa753d73c07a8326bd09c7ebfeac5d8054f601e69b657` | `86b092d0c1d498390ab171124c5e29ac14ef0e78df056a18a0ecbaaec0104d3c` | strict object metadata for anchor state/budget/graph/decisions |
| `spark.schema.json` | `d972310cb407853d57bd9b75a55e922bfdebe951971bfa5c7a93a40a0c764a9e` | `b9f5ffef407d8a477fc1daa2b4e401bc7b57733949f8a6268720a97bc78f1db6` | required `detail`, nullable `detail`, valid hash pattern |

## Frozen K=3 run

| Replicate | Arm | Hidden outcome | Candidate | Binding failure |
|---|---|---|---|---|
| replicate_001 | LUNA_FULL | `NOT_RUN_NO_CANDIDATE` | `False` | full response status was blocked |
| replicate_001 | SOL_FULL | `NOT_RUN_NO_CANDIDATE` | `False` | full response status was blocked |
| replicate_001 | LUNA_SPARK_NO_ANCHOR | `NOT_RUN_NO_CANDIDATE` | `False` | planner did not spawn |
| replicate_001 | LUNA_SPARK_CORRECT_ANCHOR | `NOT_RUN_NO_CANDIDATE` | `False` | C:\Users\BAM-Desktop\.codex\worktrees\4263\Residue\experiments\luna_sol_anchor_replication_v2\run\run_20260715T212046Z\benchmark\replicate_001\split_prelude\base |
| replicate_002 | SOL_FULL | `NOT_RUN_NO_CANDIDATE` | `False` | full response status was blocked |
| replicate_002 | LUNA_FULL | `NOT_RUN_NO_CANDIDATE` | `False` | full response status was blocked |
| replicate_002 | LUNA_SPARK_NO_ANCHOR | `NOT_RUN_NO_CANDIDATE` | `False` | planner did not spawn |
| replicate_002 | LUNA_SPARK_CORRECT_ANCHOR | `NOT_RUN_NO_CANDIDATE` | `False` | C:\Users\BAM-Desktop\.codex\worktrees\4263\Residue\experiments\luna_sol_anchor_replication_v2\run\run_20260715T212046Z\benchmark\replicate_002\split_prelude\base |
| replicate_003 | LUNA_FULL | `NOT_RUN_NO_CANDIDATE` | `False` | full response status was blocked |
| replicate_003 | SOL_FULL | `NOT_RUN_NO_CANDIDATE` | `False` | full response status was blocked |
| replicate_003 | LUNA_SPARK_CORRECT_ANCHOR | `NOT_RUN_NO_CANDIDATE` | `False` | planner did not spawn |
| replicate_003 | LUNA_SPARK_NO_ANCHOR | `NOT_RUN_NO_CANDIDATE` | `False` | C:\Users\BAM-Desktop\.codex\worktrees\4263\Residue\experiments\luna_sol_anchor_replication_v2\run\run_20260715T212046Z\benchmark\replicate_003\split_prelude\base |

No candidate was admitted and no hidden grade was run. The full-agent responses were schema-valid but reported `blocked` because their isolated shells lacked Python for the named visible validators. The three initial planner responses were schema-valid but failed the frozen controller policy because `action=spawn` was paired with `anchor_patch=null`; the matched correct-anchor forks then remained unavailable. No Spark benchmark hand was dispatched.

## Failure accounting

- Transport: all 9 benchmark calls exited `0` with final responses; the preflight also exited `0`.
- Custody: no subject changed an out-of-scope file; the correct-anchor fork encountered a controller-side prelude reuse error after the shared initial planner policy failure.
- Role: no role violations were recorded.
- Schema: all 9 benchmark final responses passed the repaired schema audit; all three production schemas passed the recursive gate.
- Visible validators: 6 full-agent calls were blocked/not admitted because the subject sandboxes had no Python interpreter; no visible validator result was admitted.
- Grader: `0` hidden grades, `12` `NOT_RUN_NO_CANDIDATE` arm dispositions, and no paired comparison receipts.
- Usage by model: `gpt-5.6-luna` 6 benchmark calls, `gpt-5.6-sol` 3 benchmark calls, `gpt-5.3-codex-spark` 0 benchmark calls plus 1 administrative preflight.

## Verdict

`PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT`. This rerun does not answer the control question and does not support either Sol replication or an anchor causal signal. The prior schema rejection remains an administrative specification defect, not a model failure, and is unchanged.

## Evidence

- Administrative preflight: `admin_preflight/` under this run.
- New manifest, frozen schedule, raw calls, responses, outcomes, and comparison: `benchmark/`.
- Content-blind posthoc schema audit: `benchmark/schema_validation_audit.json`.
- Machine-readable closure: `final_receipt.json` at the run root.
- Schema repair diff: `experiments/luna_sol_anchor_replication_v2/schema_repair_v2_1.json`.
