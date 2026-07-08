# Cross-provider reproduction attempt — Codex / GPT

Date: 2026-07-07

Evidence label: `single-source, cross-provider` where a valid candidate was produced and hidden-graded. This run was performed from a Codex/GPT environment, not an Anthropic model container.

## Valid task set

The valid hidden-grader task set is now exposed by `python experiments/breadth/breadth_tasks.py`, which prints task01, task02, and task06 from `experiments/tier-uplift`.

I did not use `tasks/*.json`, task03, task04, task05, or task07 for scoring.

## Execution constraints and honesty notes

- Direct `capability_harness.backends.openai_backend(...)` execution was not possible in this environment: there is no `OPENAI_API_KEY` and the `openai` Python package is not installed.
- I used `gpt-5.4-mini` Codex sub-agents as the cheap GPT solver path.
- The Codex sub-agent interface did not expose per-call token or cost accounting, so `input_tokens`, `output_tokens`, and `cost_usd` are logged as `0` with an explicit `token_accounting=unavailable` note. These rows are **not cost-reconciled** and must not be used for economy claims.
- Some sub-agents ignored the candidate-only prompt and returned PR-style summaries claiming hidden-grader execution. Those rows are logged as `error`/void and are not counted as valid reproduction evidence.
- Hidden graders were used only after a solver response was produced. Valid solver prompts contained the subject/spec/visible tests only, not hidden tests or answer keys.

## Outcomes

| task | solo result | harness-style result | Anthropic map | match / divergence |
| --- | --- | --- | --- | --- |
| task01 parse_duration | 2 valid GPT solo candidates cleared hidden `38/38`; 1 trial void. | 3/3 harness-style GPT candidates cleared hidden `38/38`. | Haiku/Sonnet/Opus solo all `38/38`; no gap. | Matches the committed map: no meaningful gap on task01. |
| task02 wildcard_match | 2 valid GPT solo candidates cleared hidden oracle `10681/10681`; 1 trial void. | 2 valid harness-style candidates cleared `10681/10681`; 1 trial void. | Haiku/Sonnet/Opus solo all `10681/10681`; no gap. | Matches the committed map: no meaningful gap on task02. |
| task06 select | 1 GPT solo trial found a valid counterexample: `items=[(10,0),(9,0),(8,1),(7,1),(6,1)]; k=3`, subject `None`, reference `21`. | 1 harness-style trial produced an invalid counterexample: `items=[(1,100),(1,99),(0,98),(0,97)]; k=2`, subject `1`, reference `1`; also includes invalid zero-value items. | Anthropic map: Haiku solo failed; Sonnet/Opus found; Haiku empirical-search harness found. | Diverges on the sampled solo result: cheap GPT found task06 solo in this trial. Harness-style sampled result failed; this is not comparable to the Anthropic empirical-search condition because direct executable `openai_backend`/search harness was unavailable. |

## Bottom line

This PR should be read as a **partial cross-provider reproduction artifact**, not a complete K=3, cost-reconciled benchmark. It does close one important honesty loop: a GPT-run, hidden-graded sample agrees with the Anthropic map on task01/task02 saturation, and it records a task06 divergence where cheap GPT found a counterexample solo in the sampled trial.

It does **not** support cost-per-success claims because token/cost telemetry was unavailable from the sub-agent interface.
