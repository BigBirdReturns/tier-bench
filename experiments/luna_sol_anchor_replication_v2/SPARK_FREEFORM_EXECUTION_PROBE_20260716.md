# Spark Free-Form Execution Probe, 2026-07-16

## Purpose and boundary

After five versioned experiment attempts ended `PARTIAL`, the operator directed
free-form testing before any further fixed-gate run. These probes test execution
interfaces only. They use synthetic files and tasks, no frozen benchmark task,
no hidden vectors, no grading, and no comparison rule. They support no
capability verdict.

## Calls and results

Twenty-one fresh `gpt-5.3-codex-spark@low` calls were made through the exact
authorized CLI 0.144.5 identity.

### Surface-isolation matrix: 0/9

Evidence: `run/spark_freeform_prompt_probe_20260716T232807Z/`

Three repetitions each used minimal prompting, raw-byte self-verification, and
an executable local validator. All nine calls exited 0 but changed no files.
Their events show that `--ignore-user-config` removed the effective writable
Windows command-policy surface: Spark attempted appropriate writes, but the CLI
rejected them as `blocked by policy` / read-only.

This is an execution-surface failure, not a prompt or Spark-editing failure.

### App-inherited free-form matrix: 8/9

Evidence: `run/spark_freeform_app_inherited_probe_20260716T233049Z/`

The identical tasks were rerun without `--ignore-user-config` or
`--ignore-rules`, retaining `--sandbox workspace-write`, no output schema, and
external file/diff validation.

- minimal outcome-only prompt: 2/3;
- raw-byte self-verification prompt: 3/3;
- executable local-validator prompt: 3/3.

Every call changed only `value.txt` and preserved the forbidden and validator
files. The one minimal-prompt failure wrote literal bytes `31 60 6e` (`1` plus
the two characters backtick and `n`) instead of `31 0a`. Both strategies that
made acceptance mechanically observable were 3/3.

### Planner-authored code handoff: 3/3

Evidence: `run/spark_planner_handoff_probe_20260716T233404Z/`

The current agent acted as planner and sent Spark a normal-text handoff with:

- a bounded Python implementation objective;
- one allowed file, `src/solution.py`;
- explicit forbidden files;
- an exact executable validator command using the controller Python;
- instruction to finish only after the validator exited 0;
- no JSON response schema or structured report requirement.

All three calls changed exactly `src/solution.py`, preserved every forbidden
file, and independently passed the external validator. Durations were 11.176,
11.436, and 11.545 seconds.

## Finding

The best observed interface is:

1. A stronger model plans and emits a bounded execution handoff.
2. Spark receives that handoff as a free-form execution prompt on the
   app-inherited writable CLI surface.
3. The handoff includes the exact acceptance command and allowed/forbidden
   paths.
4. Spark edits and runs the validator without an output schema.
5. The controller ignores report prose, evaluates the actual Git diff and
   validator result, and creates the structured receipt itself.

The fixed Spark response schema was not helping execution correctness. Hiding
the validator behind `controller-owned` semantics also denied Spark the fastest
feedback loop. Conversely, removing the app-inherited config made every write
fail regardless of prompt quality.

## Scientific consequence

These probes do not retroactively rescue the failed v2.2.2 canary and do not
authorize a benchmark retry. They provide empirical design evidence for a new,
prospective execution-interface protocol.
