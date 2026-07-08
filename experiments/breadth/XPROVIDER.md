# XPROVIDER — Codex/OpenAI reproduction

Evidence label: `single-source, cross-provider` for the blocked setup record only. Successful keyed runs will produce measured generation and grade rows under the same account/model discipline.

## Status

A real OpenAI reproduction requires a provider key because the protocol requires a cheap GPT solver, real token usage, and real cost telemetry. This execution environment still has no provider key, so no benchmark outcomes are claimed in this file.

This PR adds `experiments/breadth/xprovider_run.py` so the next keyed run is executable rather than merely described. The runner performs the requested K=3 solo and K=3 harness trials against exactly the hidden-grader breadth tasks and invokes hidden graders only after candidate generation.

The committed ledger row is a setup-blocker row only. It is not benchmark evidence and it must not be counted as a pass/fail result.

## How to run the reproduction

Run `python experiments/breadth/xprovider_run.py --model gpt-4.1-mini --k 3` in an environment with provider credentials available.

The runner uses the OpenAI Chat Completions API directly so it can capture provider usage for each call. Cost is computed from observed usage and model prices in `models.json`. If OpenAI reports cached input tokens, the runner records them as `cache_read_tokens`; if the registry lacks a cached-input price, cached tokens are conservatively priced at the full input rate and marked with `cache_pricing="full_input_rate_assumed"`.

## Evidence model

The runner splits generation evidence from grading evidence:

- Provider rows are logged immediately after each OpenAI response returns and before any hidden grader runs.
- Provider rows use non-verdict outcomes such as `generated` and phases such as `solo_generate`, `harness_lens_N`, and `harness_synthesize`.
- Each solver attempt gets a stable `attempt_id` in `extra`.
- Hidden-grader rows are separate zero-token, zero-cost rows with phases such as `solo_grade` and `harness_grade`.
- Grade rows link back to provider rows through `extra.parent_attempt_id` and record `candidate_sha256`.
- Grader timeouts or crashes become `error` grade rows instead of erasing already-logged generation spend.

## Protocol boundaries enforced by the runner

- Valid tasks are exactly the tasks printed by `python experiments/breadth/breadth_tasks.py`:
  - `task01_parse_duration`
  - `task02_wildcard`
  - `task06_select`
- Solver prompts include only public task material: `spec.md`, `subject.py` when present, and `visible_tests.py` when present.
- Hidden graders are never inserted into prompts.
- Harness trials use `capability_harness.review(..., lenses=all_lenses())` before a synthesis call.
- Every model call is logged through `experiments.breadth.ledger.log_call` with account, model, phase, trial, tokens, cost, latency, and non-verdict generation outcome.

## Current outcomes

| Task | Hidden grader | Solo outcome | Harness outcome |
|---|---|---:|---:|
| `task01_parse_duration` | `hidden_tests.py` | not run | not run |
| `task02_wildcard` | `hidden_oracle.py` | not run | not run |
| `task06_select` | `grader.py` | not run | not run |

There are currently no valid matches or divergences to report against the Anthropic map because the OpenAI solver calls have not been run in this keyless environment.
