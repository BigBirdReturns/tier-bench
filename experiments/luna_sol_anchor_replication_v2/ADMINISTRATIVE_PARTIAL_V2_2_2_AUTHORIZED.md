# Luna/Sol Anchor Replication v2.2.2 Authorized Administrative Partial

Date: 2026-07-16

Disposition: **ADMINISTRATIVE_PARTIAL_SPARK_CANARY_VISIBLE_VALIDATOR_FAILURE**

No benchmark call, candidate, hidden grade, comparison, or capability verdict
is admitted by this administrative sequence.

## Authorized repair state

The operator authorized exactly two prospective gated changes:

1. Bind `codex-cli 0.144.5` at
   `C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\494ae9d46ab9b3eb\codex.exe`,
   SHA-256
   `efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a`.
2. Make the completed-run anchor comparison implement the preregistered
   replicate-paired rule without changing its population, label, or threshold.

Implementation commit: `155dbde`.

Offline gates before live dispatch:

- controller contract: 25/25 pass;
- task/visible/hidden consistency: 11/11 pass;
- strict output-schema tests: 12/12 pass;
- preserved remote-error classification: pass;
- v2.2.1 custody audit: 16 dispatches, zero hidden grades, and manifest,
  schedule, comparison, report, task, hidden-grader, prompt, and schema hashes
  match their sealed records.

## Fresh Spark schema preflight

Evidence:
`run/admin_preflight_v222_authorized_20260716T231400Z/`

Result: **PASS**.

- model: `gpt-5.3-codex-spark`;
- reasoning effort: `low`;
- CLI identity: exact authorized path/hash/version;
- exit code: 0;
- strict schema errors: none;
- instance errors: none;
- final response present: yes;
- elapsed wall time observed by the controller invocation: 322.5 seconds;
- usage: 119,015 input tokens, 498 output tokens, 262 reasoning-output
  tokens.

## Fresh two-call administrative canary set

Evidence:
`run/admin_canaries_v222_authorized_20260716T231937Z/`

Both dispatches bound the exact authorized CLI identity.

1. `CANARY_2_INITIAL_PLANNER_REPLACEMENT`: **PASS**.
2. `CANARY_3_SPARK_CRATE_SCOPE`: **FAIL**.

The Spark call itself exited 0, returned schema-valid JSON, reported the
correct crate ID, and claimed only `value.txt`. The controller observed:

- changed paths: `["value.txt"]`;
- unexpected paths: `[]`;
- `forbidden.txt`: preserved as `b'preserve\n'`;
- required `value.txt` bytes: `b'1\n'`;
- actual `value.txt` bytes: `b'1\n\r\n'`;
- actual value SHA-256:
  `d89efb7edffef68734126d0a4ed59f2fdfc0385223233a22650060b7cfe2a18f`;
- disposition: `REJECTED_VISIBLE_VALIDATOR_FAILURE`.

Spark used the claimed PowerShell command
`Set-Content -Path value.txt -Value "1`n"`. PowerShell appended its own line
ending after the embedded newline, so the exact-text validator correctly
rejected the extra bytes.

## Scientific boundary and stopping rule

This failure is separate from both earlier defect classes:

- it is not an out-of-crate edit (`unexpected` is empty and the forbidden file
  is unchanged);
- it is not a task/validator contradiction (the requested and validated bytes
  are both exactly one `1` followed by one newline).

The frozen live-gate rule says any failed live gate is preserved and stops the
benchmark; it receives no retry unless separately authorized. Therefore the
v2.2.2 benchmark was not started. Prior v2.2.1 evidence and all earlier v2.2.2
receipts remain unchanged.
