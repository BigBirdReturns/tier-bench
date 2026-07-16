# Luna v2.2.1 corrected rerun — administrative and benchmark closure

Status: `PARTIAL_UNPAIRED_NO_CAPABILITY_VERDICT`

The invalid `agents.max_depth=0` requirement was removed. Production and administrative dispatches now use:

```text
features.multi_agent=false
agents.max_depth=1
agents.max_threads=1
```

The planner schemas retain explicit primitive `type` declarations for `action`.

## Sealed steps

- Repair commit `c42cb59`: corrected CLI isolation configuration and refreshed contract gate.
- Repair commit `6ab8d47`: fixed the Python manifest boolean introduced during that correction.
- Repair commit `2151759`: made failed shared preludes idempotent and exposed validation errors in comparison rows.
- Strict schema validation passed for all five production schemas.
- Contract gate passed, including the corrected command-vector assertion and failed-prelude reuse witness.
- The first corrected schema proof failed only after five upstream stream-disconnect retries; its raw receipt is preserved under `run/admin_preflight_v221_corrected_20260716T002734Z/`.
- The retry passed with exit code 0, final JSON present, and zero schema or instance errors under `run/admin_preflight_v221_corrected_retry_20260716T003225Z/`.
- Replacement Canary 2 passed in one call under `run/admin_canary_v221_corrected_20260716T003240Z/`. Canary 1 was not rerun.

## Benchmark disposition

The frozen benchmark completed under `run/run_v221_corrected_20260716T003429Z/` using the repaired configuration. It made 15 scheduled calls, admitted zero candidates, and ran zero hidden grades.

The zero-candidate result is not a capability verdict. The immutable task text requires eligible priority-2 waivers to reduce fees, while the immutable visible validator expects the same waiver to produce zero relief. The full-agent candidates followed the task contract and were rejected by that contradictory visible expectation. Spark arms also produced some out-of-crate edits, which the controller correctly rejected.

The run therefore remains partial and unpaired. The task/validator contradiction requires a separately authorized task or validator repair; this closure does not alter either.
