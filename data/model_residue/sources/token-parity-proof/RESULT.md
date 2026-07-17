# Token-parity proof

Both arms started from commit `7f253b184405eb40d1cd7aebe21ca4fa7db1c25c`, where `python -m unittest -v` fails two tests with `NotImplementedError`. Both final arms independently pass 2/2 tests, and `ledger.py` is the only tracked file changed.

## Measured result

| Arm | Cloud input | Cloud output | Cloud total | Local planner | All-model total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct single session | 104,835 | 1,195 | 106,030 | 0 | 106,030 |
| Local planner -> repo crate -> fresh cloud executor | 97,773 | 902 | 98,675 | 615 | 99,290 |

The delegated route uses 7,355 fewer cloud tokens (6.94% below direct). Counting the local planner's 500 prompt and 115 generated tokens too, it uses 6,740 fewer total model tokens (6.36% below direct).

`output_tokens` already includes any reasoning tokens reported as its subset, so reasoning is not added again.

## Boundary result

A cloud planner is not viable for parity in this environment: its diagnostic call used 83,017 tokens before execution. Combined with the measured executor it would be 181,692 tokens, 71.36% above direct. Moving only bounded planning to local Qwen is the nearest-boundary fix that preserves the planner -> repository -> fresh executor shape.

## Evidence

- `direct-call/events.jsonl`: direct session events and `turn.completed` usage.
- `local-planner-call/receipt.json`: local Qwen token counts.
- `delegated-local/.cart0/plan.md`: durable repo-addressed crate.
- `executor-local-call-2/events.jsonl`: successful fresh executor events and usage.
- `executor-local-call/events.jsonl`: first executor transport attempt; it failed before any `turn.completed` usage record and made no source change.
- `planner-call/events.jsonl`: cloud-planner diagnostic showing why that boundary cannot reach parity.

The successful executor read `.cart0/plan.md`, read the three repository pointers, ran the failing validator, edited only `ledger.py`, and reran the same validator to 2/2 passing. The controller then independently reran both final arms to 2/2 passing.

## Local-executor improvement probe

The same failing commit was also given directly to each installed local model as a bounded `ledger.py` replacement task. The controller applied each returned file and ran the real validator.

| Local executor | Prompt tokens | Generated tokens | Total | Cloud tokens | Validator |
| --- | ---: | ---: | ---: | ---: | --- |
| `qwen2.5:7b` | 417 | 124 | 541 | 0 | 2/2 pass |
| `qwen3.5:9b-q4_K_M` with `think:false` | 425 | 133 | 558 | 0 | 2/2 pass |

The first Qwen 3.5 attempt omitted `think:false`; it consumed the 700-token generation limit in thinking and returned no file. Setting `think:false` fixed that observed boundary, and the rerun produced a passing implementation. These fixture results prove a zero-cloud fast path for this task, not general unattended-coding reliability.

## Controller proof

`local-first/local_first.py` ran the full fast path against a fresh copy of the failing commit. It observed the two baseline errors, used `qwen2.5:7b` for 810 prompt plus 145 generated tokens, edited only `ledger.py`, and passed the same validator with zero cloud tokens.

A forced unavailable-model run exercised the stop path: the controller exited `2`, restored `ledger.py` to its exact pre-run SHA-256, and wrote `.cart0/plan.md`. It did not launch a cloud model. The already-measured crate-to-Terra run above remains the real evidence for the separate cloud-executor boundary.

## GPU-free cloud gains

A lean full Terra agent (`--ignore-user-config`, `--ignore-rules`, plugins/apps/browser/multi-agent disabled) passed at 49,894 input plus 798 output tokens: 50,692 total, 52.19% below direct and 48.63% below the standard crate executor.

A bounded read-only Terra candidate call then returned only `ledger.py`; the controller applied it and the independent validator passed. The manual probe used 8,791 tokens, 91.71% below direct. The integrated `--skip-local --cloud-candidate` controller path independently passed with 9,151 tokens in 7.6 seconds end to end, 91.37% below direct. If this bounded candidate fails validation, the controller restores the original bytes and writes the full-agent crate.

Spark 5.3 (`gpt-5.3-codex-spark`) was then measured on the same path because its usage is on a separate account timer. It passed independently at 6,926 tokens in 5.20 seconds. After making Spark the controller default and adding a three-attempt validator-driven refinement loop, the default path passed on attempt 1/3 at 7,238 tokens in 3.91 seconds. Terra is now the full-agent escalation rather than the refinement-loop default.

## Sol versus Sol plus Spark

Sol alone passed at 9,147 Sol tokens in 6.916 seconds. A sequential Sol-plan-to-Spark pipeline passed but used 8,886 Sol tokens plus 7,565 separate Spark tokens and took 15.131 seconds; the 2.85% Sol-token saving did not justify the 118.78% wall penalty.

The corrected bounded-hog-wild shape launched Sol and Spark concurrently on isolated clones. Spark produced the first independently validated pass at 5.605 seconds; Sol passed at 8.090 seconds. This reduced time to first pass by 30.72% versus Sol in the same race. Both timers were consumed because loser cancellation is not yet implemented, so the mode is reserved for high-uncertainty work rather than default refinement.
