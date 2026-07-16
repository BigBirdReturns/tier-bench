# Luna/Sol Anchor Replication v2.2.2 CLI-Surface Decision Proposal

Date: 2026-07-16

Current disposition: **PRE_DISPATCH_BLOCK_MISSING_FROZEN_CLI**

The approved prospective task/visible repair and every offline deterministic gate are green at commit `1fc65f2`. The first live administrative step stopped before dispatch because the exact executable used by v2.2.1 no longer exists:

- required path: `C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\3135b80b111fd431\codex.exe`
- required SHA-256: `2caacad1f7b8b3e9b2527b9bff9630cfbb30ec25d8d8c018c9d55a2bec348032`
- required version: `codex-cli 0.144.2`

The installed Microsoft Store resource is not an admissible implicit substitute. Its SHA-256 is `efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a`, direct standalone execution is ACL-denied, and its bytes differ from the frozen CLI. The block receipt records zero provider/model/Spark calls and zero packet disclosures.

## Exact decision required

Choose one of these mutually exclusive paths:

1. Restore the exact `codex-cli 0.144.2` executable with SHA-256 `2caacad1f7b8b3e9b2527b9bff9630cfbb30ec25d8d8c018c9d55a2bec348032` at its recorded path. This requires no experiment-contract amendment.
2. Explicitly authorize a prospective CLI-surface amendment for v2.2.2 using a newly runnable standalone CLI whose absolute path, full executable chain, version, and hashes are frozen before any provider call. This changes only the administrative execution surface; it does not authorize changes to task, validator, grader, schedule, models, budgets, prompts, schemas, hidden vectors, or comparison rules.

No authority currently permits path 2, and the repository cannot perform path 1 without the missing bytes or an external installation/restoration action.

## Additive app-to-CLI diagnostic, 2026-07-16

After this proposal was written, the Codex app command environment exposed a
runnable user-space copy of the current executable:

- candidate path: `C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\494ae9d46ab9b3eb\codex.exe`
- candidate SHA-256: `efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a`
- candidate version: `codex-cli 0.144.5`

The operator authorized Spark-only diagnostic calls before any benchmark
start. With that candidate path explicitly substituted at invocation time,
`gpt-5.3-codex-spark` at `low` reasoning passed both the strict union-schema
smoke and the synthetic one-file crate-scope smoke. Raw evidence and the
non-verdict boundary are recorded in
`SPARK_APP_CLI_BRIDGE_SMOKE_20260716.md` and its referenced run directories.

This diagnostic establishes that the app can launch a child CLI process which
dispatches to Spark. It does not by itself authorize path 2 for the frozen
benchmark. If path 2 is chosen, this exact candidate identity is now the
minimal known runnable surface to freeze and test prospectively.

## Affected files for path 2

- `experiments/luna_sol_anchor_replication_v2/run_v2.py`
- `experiments/luna_sol_anchor_replication_v2/scripts/run_schema_preflight.py`
- `experiments/luna_sol_anchor_replication_v2/scripts/run_v222_canaries.py`
- a new additive CLI-surface freeze receipt under `experiments/luna_sol_anchor_replication_v2/`
- regenerated prospective `controller_contract_gate_v222.json`
- `docs/agents/QUEUE.md`

No v2.2.1 file or completed-run receipt would be edited.

## Proposed minimal diff for path 2

1. Replace the two obsolete hard-coded CLI constants with one exact newly authorized absolute path.
2. Bind its executable SHA-256 and `--version` output in the CLI-surface receipt and every preflight/canary/benchmark manifest.
3. Require the Spark schema preflight, Luna planner canary, Spark crate-scope canary, and benchmark runner to resolve to the same path and SHA-256; fail before dispatch on any mismatch.
4. Record the prior CLI identity as superseded for v2.2.2 administrative execution only.

## Regression tests

- Missing or hash-mismatched CLI fails before run-root creation and before dispatch.
- Preflight/canary/benchmark CLI identities must match exactly.
- The 17-test controller contract gate remains green.
- The 11-test task/visible/hidden consistency gate remains green.
- Strict production schema tests remain 12/12 green.
- The v2.2.1 custody audit remains 16 dispatches, zero candidates, zero hidden grades, with all sealed hashes matching.

## Rerun gates

1. Re-run all offline deterministic and custody gates.
2. Make one fresh Spark union-schema preflight call.
3. Make exactly two unscored live canary calls: the frozen Luna initial-planner canary and the synthetic Spark one-file crate-scope canary.
4. Commit the green administrative receipts and bind their commit as `suite_commit`.
5. Only then execute one fresh v2.2.2 benchmark run using the unchanged schedule, models, budgets, prompts, schemas, task, hidden grader, and comparison formulas.

Any failed live gate is preserved and stops the benchmark. It is not capability evidence and receives no retry unless separately authorized by the existing stopping rules.

## Evidence-preservation requirements

- Preserve all v2.2.1 raw outputs and receipts byte-for-byte.
- Preserve `run/admin_preflight_v222_20260716T220438Z_pre_dispatch_block.json` as the zero-call missing-CLI record.
- Use unique output directories; never overwrite a failed or completed gate/run.
- Preserve exact command vectors, raw JSONL, stderr, final-response bytes, completion receipts, executable identities, and hashes.
- Never reinterpret an administrative partial as a benchmark or capability verdict.
