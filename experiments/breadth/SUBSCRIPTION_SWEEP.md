# ChatGPT UI subscription-surface breadth sweep

This sweep turns raw ChatGPT UI answers into complete, auditable benchmark evidence. It does **not** run more prompts and it does **not** claim a full matrix result until raw UI output is captured and locally graded.

## Sparse selector matrix

The ChatGPT UI is treated as a two-axis selector matrix: model family plus intelligence. The observed editable inventory lives in `subscription_models.example.json`; it is not a universal availability claim.

Observed exposed cells:
- GPT-5.5 / Instant, Medium, High
- GPT-5.4 / Instant, Medium, High
- GPT-5.3 / Instant
- o3 / High

Observed unavailable/not exposed cells:
- GPT-5.3 / Medium, High
- o3 / Instant, Medium

## Workflow

A. Generate the public prompt packet:

```bash
python experiments/breadth/subscription_run.py --model-family GPT-5.5 --intelligence Medium --task-id task01_parse_duration --trial 1 --out /tmp/capture_packet.json
```

B. In the ChatGPT UI, select the exact family/intelligence cell, for example `GPT-5.5 / Medium`.

C. Paste the packet's `prompt_text` into a fresh chat. Never paste hidden grader or oracle content.

D. Copy the exact raw answer into `raw_output`. Record selector metadata, visible thought seconds when actually visible, screenshot hash when available, and quota status.

E. Ingest capture JSONL. The ingest script hashes prompt and raw output, extracts a candidate, classifies format compliance, runs the local hidden grader only after extraction, appends a ledger row, writes normalized captures, and emits a matrix summary:

```bash
python experiments/breadth/ui_capture_ingest.py captures.jsonl \
  --ledger experiments/breadth/run/subscription_ledger.jsonl \
  --normalized-out experiments/breadth/run/normalized_captures.jsonl \
  --matrix-out experiments/breadth/run/subscription_matrix.json
```

F. Log unavailable selector cells as blocked evidence packets with `phase="availability"`, `trial=0`, `quota_status="not_exposed_in_ui"`, and empty `raw_output`. These rows have `outcome="blocked"`, zero tokens/cost, no candidate hash, and no pass/fail claim.

## Ledger evidence fields

Every ingested UI row carries `surface="chatgpt_ui_subscription"`, `selected_model_family`, `selected_intelligence`, `selected_model_label`, `telemetry_class="subscription_surface"`, `token_accounting="unavailable"`, `cost_accounting`, `quota_status`, `prompt_sha256`, `raw_output_sha256`, `candidate_sha256` when extraction succeeds, `capture_id`, `format_compliance`, `extraction_status`, optional `visible_thought_seconds`, and optional `screenshot_sha256`.

Token counts and costs are zero unless exact UI telemetry is supplied; default accounting marks tokens unavailable and cost as subscription quota/unavailable.

## Format compliance

The classifier records one of:
- `raw_function_only`
- `extractor_needed_markdown_fence`
- `extractor_needed_prose`
- `malformed_no_candidate`
- `counterexample_exact`
- `counterexample_extracted`

For task01/task02, the expected raw output is a single Python function only. Markdown fences or prose are format violations, but code may still be extracted and graded. For task06, the expected raw output is exactly `items=[...]; k=...`; prose is a format violation, but a counterexample may still be extracted and checked.

## Evidence discipline

Do not fabricate token counts, costs, screenshots, thought seconds, hidden reasoning, availability, or pass/fail results. Operator-reported outcomes are not benchmark results unless raw output is present and locally graded. The ingest path must not modify `experiments/tier-uplift/`.
