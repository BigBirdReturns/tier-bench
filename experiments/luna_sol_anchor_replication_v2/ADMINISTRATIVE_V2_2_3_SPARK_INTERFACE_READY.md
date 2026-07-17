# Luna/Sol Anchor Replication v2.2.3 Administrative Spark Interface

Date: 2026-07-16/17 UTC

Disposition: **ADMINISTRATIVE INTERFACE GREEN; BENCHMARK NOT AUTHORIZED OR RUN**

## Current state

The operator-authorized v2.2.3 administrative interface is implemented at
suite commit `6ff12d5f7932da0759f034f0180fcd64e182934f`.

- Planner and full-agent calls remain structured and schema-bound.
- Spark execution calls use `gpt-5.3-codex-spark` free-form on the
  app-inherited `workspace-write` CLI surface.
- Spark execution uses no output schema, `--ignore-user-config`, or
  `--ignore-rules`.
- Each handoff contains the unchanged visible task text, controller-validated
  crate bounds, budgets, stop condition, and exact executable validator
  command.
- Candidate admission ignores Spark final prose. The controller observes the
  Git diff, rejects out-of-crate paths, reruns the visible validator, applies
  an admitted patch to a clean copy, and writes the structured receipt.
- The benchmark entrypoint is fail-closed pending a separate explicit
  authorization.

## Prior contradiction and evidence disposition

The v2.2.1 task/visible-validator contradiction and its v2.2.2 minimal repair
remain preserved. The failed v2.2.2 Spark canary, all five partial versioned
attempts, both v2.2.2 administrative block sequences, and all 21 free-form
probe calls are unchanged. No partial or exploratory result is reinterpreted
as capability evidence.

The separate Spark out-of-crate issue is handled mechanically: a passing
validator cannot override an unexpected path. The deterministic gate covers
solution/forbidden-path, validator, and task mutation, plus no-diff and failing
validator cases.

## Frozen interface

- CLI path: `C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\494ae9d46ab9b3eb\codex.exe`
- CLI SHA-256: `efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a`
- CLI version: `codex-cli 0.144.5`
- Surface receipt: `SPARK_EXECUTION_SURFACE_V2_2_3_FREEZE.json`
- Surface receipt SHA-256: `284a3f0aa0f468378d7f804cdabd9be1105ce2f460407a29e11e00699af9f3e1`

## Offline gates

`controller_contract_gate_v223_authorized.json` passed 37/37 deterministic
checks. It includes fresh task/visible consistency, strict planner parsing,
controller admission and custody, incomplete-collection suppression, and the
unchanged paired-comparison rule.

- Controller gate SHA-256: `6aa36bab6d5814431eb04c94c03497c09c8a450666b314038c53261f229b6e12`
- Existing strict output schemas: 5/5 valid
- Benchmark entrypoint: refused before any task, schedule, or model dispatch

## Synthetic live canaries

Run directory:
`run/admin_canaries_v223_spark_20260717T000024Z`

- Calls requested/completed: 3/3
- Model: `gpt-5.3-codex-spark`
- Result: 3/3 passed
- Spark exit codes: 0, 0, 0
- Observed changed paths: `src/solution.py` only in every replicate
- Controller visible validator: passed in every replicate
- Benchmark calls: 0
- Benchmark task loaded: false
- Capability evidence: false
- Summary SHA-256: `0e3cc1277034d8337fd5d2be3e2a9d220bae70cffc3fdea8963edbcd8dbbc839`

The actual candidate patches are preserved beside the controller receipts and
match their pre-existing receipt hashes exactly:

- replicate 001: `c06c7ecd4b6953694db002dbe645ef8bad632d71faf814328aeb5a0470ded786`
- replicate 002: `27cc7a14e3c115015270a420d1bc4f97aeb82868bfe70cfb463002ccc30d3b3c`
- replicate 003: `c41b773b099f85f97135bc5312922e79bf3f2f6aa1ad617fe8bd395589a6f4a7`

## Remaining decision

No benchmark command is currently admissible. The next gated decision is
whether to authorize a v2.2.3 benchmark run using this exact interface and new
versioned preflight/canary receipts. That decision must not change the frozen
task, validator, grader, schedule, models, budgets, hidden vectors, comparison
rules, or path boundaries unless separately authorized.

The exact currently admissible live command is only a new synthetic canary
run:

```powershell
$git = 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
$py = 'C:\Users\BAM-Desktop\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$suite = (& $git -C 'D:\Projects\Tier-Bench\worktrees\luna-sol-anchor-replication-v2' rev-parse HEAD).Trim()
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$out = "experiments\luna_sol_anchor_replication_v2\run\admin_canaries_v223_spark_$stamp"
& $py 'experiments\luna_sol_anchor_replication_v2\scripts\run_v223_spark_canaries.py' $out --replicates 3 --suite-commit $suite
```
