# XPROVIDER — OpenAI reproduction attempt

This file records an attempted independent cross-provider reproduction of the `experiments/tier-uplift` hidden-grader map using a cheap GPT solver. It does not report a capability result, because the OpenAI provider path was unavailable in the execution environment.

## Scope

The valid task set is the hidden-grader set named by `experiments/breadth/breadth_tasks.py`: `task01_parse_duration`, `task02_wildcard`, and `task06_select`. The visible-grader tasks and the answer-key review tasks remain out of scope.

Requested conditions were:

- solo cheap-GPT, K=3 per valid task;
- cheap-GPT plus the frozen `capability_harness` lens set, K=3 per valid task;
- solver receives only subject, spec, and `visible_tests.py`;
- hidden graders remain outside the solver prompt;
- every attempt is logged to `experiments/breadth/run/xprovider_ledger.jsonl` with account `codex-openai`.

## Result

No solver calls were made. `OPENAI_API_KEY` was absent in the execution environment, so `capability_harness.backends.openai_backend(<cheap model>)` could not be used. The ledger rows in `run/xprovider_ledger.jsonl` therefore record provider-unreachable skips with zero tokens and zero cost. They must not be counted as model failures, hidden-grader passes, hidden-grader failures, or corroborating evidence.

Hidden-grader separation was preserved. No cheap-GPT solver saw a hidden grader, because no cheap-GPT solver was successfully invoked.

## Per-task status

| task | solo cheap-GPT | cheap-GPT + harness | comparison to Anthropic map |
|---|---|---|---|
| `task01_parse_duration` | not run, provider unavailable | not run, provider unavailable | no match/divergence claim |
| `task02_wildcard` | not run, provider unavailable | not run, provider unavailable | no match/divergence claim |
| `task06_select` | not run, provider unavailable | not run, provider unavailable | no match/divergence claim |

The committed Anthropic map remains the only actual measured map for these tasks. This attempted OpenAI run is `single-source, cross-provider` as an environment-level skip record only. It does not upgrade any task cell to `corroborated`.

## Ledger

Evidence tier: blocked reproduction attempt, not a capability measurement. Venue: GPT/OpenAI-driven repository session using the GitHub connector, without an OpenAI API key exposed to the runtime. Target: cheap GPT solver through `openai_backend`, plus the frozen lens harness. Upside: the hidden-grader boundary and token ledger were not falsified. Downside: no task outcome was produced. Failure mode: treating these zero-token provider-unreachable rows as pass/fail evidence.
