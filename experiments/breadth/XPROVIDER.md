# XPROVIDER — Codex/OpenAI reproduction

Evidence label: `single-source, cross-provider`.

## Status

A real OpenAI reproduction requires an OpenAI API key because the protocol requires a cheap GPT solver, real token usage, and real cost telemetry. This execution environment still has no `OPENAI_API_KEY`, so no benchmark outcomes are claimed in this file.

To remove ambiguity and make the next run executable rather than merely described, this PR adds `experiments/breadth/xprovider_run.py`. The runner performs the requested K=3 solo and K=3 harness trials against exactly the hidden-grader breadth tasks, logs every OpenAI call to `experiments/breadth/run/xprovider_ledger.jsonl`, and invokes hidden graders only after candidate generation.

The existing ledger row is a setup-blocker row only. It is not benchmark evidence and it must not be counted as a pass/fail result.

## How to run the reproduction

```bash
OPENAI_API_KEY=... python experiments/breadth/xprovider_run.py --model gpt-4.1-mini --k 3
```

The runner uses the OpenAI Chat Completions API directly so it can capture provider usage for each call. Cost is computed from the observed prompt/completion token counts and the model prices in `models.json`.

## Protocol boundaries enforced by the runner

- Valid tasks are exactly the tasks printed by `python experiments/breadth/breadth_tasks.py`:
  - `task01_parse_duration`
  - `task02_wildcard`
  - `task06_select`
- Solver prompts include only public task material: `spec.md`, `subject.py` when present, and `visible_tests.py` when present.
- Hidden graders are never inserted into prompts.
- Harness trials use `capability_harness.review(..., lenses=all_lenses())` before a synthesis call.
- Every model call is logged through `experiments.breadth.ledger.log_call` with `account="codex-openai"`, model, phase, trial, tokens, cost, latency, and outcome.

## Current outcomes

| Task | Hidden grader | Solo outcome | Harness outcome |
|---|---|---:|---:|
| `task01_parse_duration` | `hidden_tests.py` | not run | not run |
| `task02_wildcard` | `hidden_oracle.py` | not run | not run |
| `task06_select` | `grader.py` | not run | not run |

There are currently no valid matches or divergences to report against the Anthropic map because the OpenAI solver calls have not been run in this keyless environment.
