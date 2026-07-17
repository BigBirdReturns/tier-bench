# Spark app-to-CLI bridge smoke, 2026-07-16

## Scope and disposition

This is additive administrative evidence only. The operator explicitly requested
unscored tests proving that an agent running inside the Codex desktop app can
dispatch bounded work to `gpt-5.3-codex-spark` through the authenticated
user-space CLI. These calls did not disclose the frozen benchmark task, use
hidden vectors, grade a candidate, apply comparison rules, or start the paid
benchmark. They support no capability verdict.

Disposition: **2/2 administrative Spark smoke checks passed**.

## Executable identity

- path: `C:\Users\BAM-Desktop\AppData\Local\OpenAI\Codex\bin\494ae9d46ab9b3eb\codex.exe`
- version: `codex-cli 0.144.5`
- SHA-256: `efdb3540ef74b9909408c8d38da79483454797b36f471e3e004fc2bf2b70e22a`
- model: `gpt-5.3-codex-spark`
- reasoning effort: `low`
- session persistence: disabled (`--ephemeral` and `history.persistence="none"`)
- multi-agent: disabled

The WindowsApps resource with the same binary hash was discoverable but could
not be executed directly because of its ACL. The user-space copy above was
runnable from the Codex app's command surface.

## Results

1. Strict-schema/read-only smoke
   - result: exit 0; final response present; strict schema valid; instance valid
   - usage: 9,341 input; 712 output; 468 reasoning output tokens
   - evidence: `run/spark_app_bridge_schema_smoke_20260716T224050Z/`
   - completion: `run/spark_app_bridge_schema_smoke_20260716T224050Z/completion.json`

2. One-file crate-scope smoke
   - objective: change `value.txt` from `0` to `1`
   - allowed path: `value.txt`
   - forbidden path: `forbidden.txt`
   - result: exit 0; strict schema valid; candidate admitted; changed paths
     exactly `["value.txt"]`; unexpected paths `[]`; forbidden file preserved
   - usage: 30,103 input; 584 output; 419 reasoning output tokens
   - evidence: `run/spark_app_bridge_crate_smoke_20260716T224111Z/`
   - controller receipt:
     `run/spark_app_bridge_crate_smoke_20260716T224111Z/canary_3_spark_crate_scope/controller_receipt.json`

## Contract boundary

This proves the requested app-to-Spark transport mechanism and the bounded
crate edit behavior on a synthetic task. It does not silently rebind the frozen
v2.2.2 benchmark CLI surface. The benchmark remains blocked until the operator
decides the prospective CLI rebind described in
`CLI_SURFACE_V2_2_2_DECISION_PROPOSAL.md` and the comparison-contract repair
described in `COMPARISON_CONTRACT_V2_2_2_DECISION_PROPOSAL.md`, after which all
deterministic and administrative gates must be regenerated and pass.
