# Robust Sol versus Spark baseline

Date: 2026-07-17

## Design

- Six executable single-file Python tasks: aggregation, interval merging, dependency ordering, immutable nested changes, JSON Pointer patching, and dependency-aware scheduling.
- Three matched replicates per task.
- Eighteen paired races and 36 bounded model lanes.
- Each pair launched Sol-low once and Spark-low with up to three validator-driven attempts on isolated copies.
- Every controller success received a separate model-free validator rerun.
- Concurrency was capped at two; neither model had repository write tools.

## Aggregate result

| Metric | Sol | Spark |
| --- | ---: | ---: |
| Independent passes | 18/18 | 18/18 |
| Median wall time | 10.704 s | 7.062 s |
| Median tokens | 10,382 | 8,828.5 |
| Total tokens | 190,126 | 167,147 |

Spark won 17 of 18 paired races (94.44%; Wilson 95% interval 74.24%-99.01%). Its median wall time was 34.02% lower and median tokens were 14.96% lower. The median paired Sol/Spark speed ratio was 2.11x. Spark usage is on this account's separate Spark timer.

Both arms passed every task on their first candidate. The configured Spark refinement limit of three was never exercised, so this baseline establishes first-pass behavior but does not claim measured repair-loop quality.

## Per-task median wall time

| Task | Sol | Spark | Spark wins | Spark wall reduction |
| --- | ---: | ---: | ---: | ---: |
| changes | 6.109 s | 3.282 s | 2/3 | 46.28% |
| dependencies | 8.985 s | 3.578 s | 3/3 | 60.18% |
| intervals | 8.156 s | 6.062 s | 3/3 | 25.67% |
| JSON Patch | 28.000 s | 11.328 s | 3/3 | 59.54% |
| ledger | 10.875 s | 10.031 s | 3/3 | 7.76% |
| scheduler | 32.735 s | 11.500 s | 3/3 | 64.87% |

## Decision

Routine bounded execution should use Spark first. Always racing Sol adds Sol-timer consumption while changing the winner in only 1/18 cases on this workload. Use Sol after a Spark validator failure, or concurrently only when an independent high-risk cross-check is worth the extra timer.

This baseline covers deterministic single-file Python edits. It does not establish the same result for multi-file repository work, UI tasks, migrations, or judgment-heavy changes.

## Raw evidence

- `token-parity-proof/robust-race-20260717T1340/results.jsonl`: 24 rows, SHA-256 `A70C2151DEC378E33B85E3492A54B46BEBC8AE184C606295EEFE798EF50B3F4A`.
- `token-parity-proof/robust-race-hard-20260717T1350/results.jsonl`: 12 rows, SHA-256 `B384690E68478630EC54105BF6E2BF23CE941EC4228E11B8F20A7CD36889B83E`.
- 36/36 retained `independent-validator.txt` files end in `OK`.
