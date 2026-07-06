# CLAUDE.md — Tier-Based Model Routing for This Project

## What This Repo Does

This is Tier Bench. It does two things:

1. **Benchmark mode**: Runs 9 deterministic coding tasks (T0-T2) against every model in your pricing table, scores them with objective validators (compile check, diff bounds, functional equivalence, test pass), and produces a routing table showing which models pass which tiers at what cost.

2. **Orchestrator mode**: Takes a plain-English request, decomposes it into subtasks using a T4 planner model, routes each subtask to the cheapest capable model, executes, and validates.

## Quick Commands

```bash
# First time setup
bash setup.sh

# Dry run (no API calls, shows cost estimates)
python orchestrator.py --dry-run "your task description here"

# Run benchmark to build your routing table
python orchestrator.py --benchmark T0
python orchestrator.py --benchmark all

# Orchestrate real work
python orchestrator.py "Fix the division by zero bug in safe_div"

# Check costs
cat llm_costs.jsonl | python -m json.tool

# View benchmark results
python scripts/compute_metrics.py

# Frontier diff: what does the driver model give you, what replicates it
python scripts/diff_report.py

# Orchestrate with an explicit driver (planner/verifier) model
python orchestrator.py --driver claude-fable-5 "your task"
```

## Tier Routing Rules

When Claude Code works in this repo, classify every task:

| Tier | What It Is | Model Alias | Max Output | Max Tools |
|------|-----------|-------------|-----------|-----------|
| T0 | Format, lint, rename | `haiku` | 500 | 5 |
| T1 | Implement from clear spec | `haiku` | 1000 | 8 |
| T2 | Fix bug, small integration | `sonnet` | 1500 | 10 |
| T3 | Review, refactor, complex debug | `sonnet` | 2000 | 15 |
| T4 | Decompose, plan, interface design | `opus` med | 3000 | 20 |
| T5 | Architecture tradeoffs | `opus` high | 4000 | 30 |

## Hard Rules

1. Start at the lowest plausible tier.
2. One attempt per tier. If it fails, escalate. Do not retry.
3. Diff limit: 250 lines unless task explicitly requires more.
4. If stuck or ambiguous, stop and ask. Do not guess.
5. Always run tests after code changes.
6. Every API call must set max_tokens matching the tier budget.

## Repo Structure

```
orchestrator.py         <- Main entry point (plan, execute, benchmark)
cost_guard.py           <- Spending limits + tier routing + pricing table
setup.sh                <- One-command setup

harness/                <- Benchmark engine
  run_suite.py          <- Run all tasks in a tier
  run_task.py           <- Run one task against all models in its tier
  validators.py         <- Deterministic checks (compile, diff, tests, equivalence)
  model_call.py         <- CostGuard-backed API calls
  task_schema.py        <- Task manifest loader
  metrics.py            <- Compute pass rates and cost-per-success
  canonical.py          <- Baseline output tracking
  util_git.py           <- Git diff measurement

tasks/                  <- Task manifests (JSON)
  t0_*.json             <- 3 clerical tasks
  t1_*.json             <- 3 junior tasks
  t2_*.json             <- 3 mid tasks

fixtures/               <- Test repos for benchmarks
  t0_format_whitespace/ <- Intentionally bad formatting
  t0_sort_imports/      <- Unsorted imports
  t0_rename_symbol/     <- camelCase to snake_case
  t1_impl_from_docstring/ <- Implement slugify() from spec
  t1_unit_test_gen/     <- Write tests for calc.py
  t1_simple_refactor/   <- Consolidate area functions
  t2_fix_failing_test/  <- Division by zero bug
  t2_api_integration/   <- Implement fetch_json client
  t2_multi_file_patch/  <- Fix normalize_name

harness/attempt.py      <- Single attempt path shared by models AND composites
harness/composites.py   <- Cascade / best-of-n / driver-repair candidates

scripts/
  compute_metrics.py    <- Parse harness_results.jsonl into routing table
  diff_report.py        <- Frontier diff: replicated / frontier-edge per tier
```

## Driver / hands

`models.json` defines `roles.driver` — the model that plans, verifies, and
repairs (judgment tokens). Execution auto-routes to the cheapest capable
model (bulk tokens). Composites in `models.json` are benchmarked as
first-class rows so replication claims carry measured prices. A failed cheap
attempt is reused as repair evidence for the driver, never discarded.

## Environment Variables

```bash
ANTHROPIC_API_KEY       # Required for Claude models
OPENAI_API_KEY          # Required for OpenAI models
HARNESS_MAX_PER_CALL    # Per-call USD limit (default: 1.00)
HARNESS_MAX_DAILY       # Daily USD limit (default: 10.00)
HARNESS_PROVIDER        # Force "anthropic" or "openai" (default: auto)
```
