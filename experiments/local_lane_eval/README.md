# Local Lane Evaluation Harness

This harness measures whether a small local model (via Ollama) can handle **schema-constrained extraction and classification** tasks. It tests structured-output capability on the lane the model passed in baseline testing.

## What It Measures

12 deterministic test cases covering:
- Filename parsing, invoice extraction, log line parsing
- Path properties, date normalization, unit parsing
- Enum classification with closed label sets and unknown fallback
- Nested objects and array fields
- Empty input handling
- Distractor-sentence rejection

Each case is graded with **exact-match determinism**: the parsed JSON object must match the expected object exactly. Order-insensitive for dict keys; types and values must match precisely.

## Quick Start

### Run Against a 9b Model

```bash
python run_eval.py --model qwen3.5:9b
```

### Run Against a 4b Model

```bash
python run_eval.py --model qwen3.5:4b
```

### Save Results to JSON

```bash
python run_eval.py --model qwen3.5:9b --out results_9b.json
python run_eval.py --model qwen3.5:4b --out results_4b.json
```

### Specify Ollama URL (if not localhost)

```bash
python run_eval.py --model qwen3.5:9b --base-url http://your.ollama.host:11434
```

## Why Exact-Match Grading?

- **Model autonomy**: The grader must not be the model under test. An LLM cannot grade itself on subjective criteria without circularity.
- **Reproducibility**: Exact match is deterministic. No variance, no judgment calls, no inference cost per case.
- **Safety**: A model that cannot produce valid JSON matching a schema cannot be trusted with structured output in production.

## Transport Failures

If the evaluation cannot reach Ollama (connection timeout, refused, malformed response), `run_eval.py` exits with code 2. This is a **skip**, not a score of 0. It indicates the harness itself is misconfigured or Ollama is down—not a model failure.

## Output Format

Each run prints:
- Per-case status: `<case-id>: ok` or `<case-id>: FAIL`
- Summary: `SCORE k/12`, median latency, total tokens consumed
- JSON export (if `--out` specified): full case results with parsed objects and expected values

## Scoring

- **Pass**: All 12 cases produce exact-match JSON. Exit code 0.
- **Fail**: One or more cases fail to match. Exit code 1.
- **Transport**: Ollama unreachable. Exit code 2.
