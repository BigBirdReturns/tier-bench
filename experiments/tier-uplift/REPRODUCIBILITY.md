# Reproducibility & telemetry manifest — tier-uplift

Honest account of what reruns identically, what is captured, and what does not.

## Models (provenance)

All runs are real model instances via the Agent tool's `model` override:

| alias | model id |
|---|---|
| haiku | `claude-haiku-4-5` |
| sonnet | `claude-sonnet-5` |
| opus | `claude-opus-4-8` |

No API keys were used; models were driven as subagents in the session environment.

## Determinism map

| artifact | reproducible? |
|---|---|
| subjects, specs, answer keys | **exact** (committed source) |
| graders: `hidden_tests.py`, `hidden_oracle.py`, `grader.py`, `visible_tests.py` | **exact** — deterministic; a given candidate always scores the same |
| analysis: `analyze.py`, `capture.py` | **exact** — deterministic given the committed run files |
| pooling/anonymization (`pool.txt`, `pool_key.json`) | **exact** — pool order is a content-`sha256` sort (no RNG), so the same candidate set always yields the same IDs |
| every reported NUMBER (scores, ρ, cost) | **exact** — regenerates from committed data via the scripts |
| the subagent OUTPUTS (candidate lines, bug reports, rankings) | **NOT reproducible** — LLM sampling; no seed control on subagents. These are a captured **snapshot**, committed under `runs/`, `gen/`, `judge/`, `exemplars/`. |

So: the **pipeline** and the **analysis of the captured outputs** are fully
reproducible; a fresh rerun of the *models* will produce different text and
therefore possibly different scores. The committed run files are the record.

## Telemetry (tokens / tool_uses / duration)

Captured per run in each task's `usage.jsonl` (token counts, tool_uses,
duration_ms as reported by the harness), joined to results and priced in
`capture.py` (cost at output-rate, labeled an upper bound).

- **task06, task07: complete** — every run's telemetry is in `usage.jsonl`.
- **tasks 01–05: partial** — per-run token/duration were reported in-session by
  the harness but not all were written to committed files at the time. This is a
  known gap; the *scores* for those tasks are fully preserved in `LEDGER.md` and
  the `runs/` outputs, but their per-run token telemetry is not committed. Future
  runs should append to a per-task `usage.jsonl` at capture time (task06/07 do).

## How to rerun

Each task's exact agent prompts are committed in its `PROMPTS.md` (task07 has the
full pipeline; other tasks follow the same review/generate/judge templates). To
reproduce:

1. Re-issue the prompts in `PROMPTS.md` to the named models (expect *different*
   text — non-deterministic).
2. Drop outputs into the task's `runs/`/`gen/`/`judge/` with the same filenames.
3. Run the task's grader + `analyze.py`/`capture.py` — deterministic from there.

To re-derive every committed number **without** re-running models, just run the
graders/analysis against the already-committed run files.
