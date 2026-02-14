# Tier Bench

Tier Bench is an empirical benchmarking system for LLM routing. It measures which models actually succeed at different task tiers and what they cost per successful outcome, then feeds that data into a cost-guarded router.

This replaces vibe-based model selection with operational data.

**[Live Pricing & Capability Cheatsheet](https://bigbirdreturns.github.io/tier-bench/)**

## The problem

Most AI tooling does this:

1. Pick a "best" model by reputation
2. Route everything to it
3. Hope the bill does not explode

That approach fails because cheap models are good at many tasks, expensive models are only needed for a few, nobody measures success rate per task tier, and token cost alone is meaningless without success probability.

Routing without measurement burns money.

## What Tier Bench does

Tier Bench treats models like infrastructure, not magic.

It runs deterministic tasks across defined tiers and records success or failure, tokens consumed, and dollars spent. From that it computes:

```
cost_per_success = average_cost / success_rate
```

Routing decisions are based on measured performance, not brand names.

## Task tiers

Tasks are grouped by what can be validated deterministically.

| Tier | Work | Tasks | Validation |
|------|------|-------|------------|
| T0 | Formatting, imports, renames. Zero logic change. | 3 | compile, ruff, functional equivalence |
| T1 | Simple functions, unit tests, docstring specs. | 3 | compile, tests |
| T2 | Bug fixes, API wiring, multi-file patches. | 3 | compile, tests, diff bounds |
| T3 | Security fixes, god function refactors, cross-module debugging. | 3 | compile, tests, AST structural checks |
| T4 | Planning, decomposition. | 0 | JSON plan validity (buildable, not built) |
| T5 | Architectural judgment. | 0 | Not benchmarked. Human review. |

Tier Bench is explicit about what it measures and what it does not.

T0 through T3 have 12 deterministic tasks with objective pass/fail. T4 and T5 ceilings are assigned by frontier positioning. The README does not pretend otherwise.

## How it works

1. `models.json` defines the live model registry. Providers, pricing, tier ceilings, routing candidates. This is the single source of truth. Edit this file to add models. Do not edit Python.

2. The harness runs deterministic fixtures per tier. Compile checks, tests, diff limits, behavior preservation.

3. The orchestrator decomposes plain-English requests into tiered subtasks. It injects repo context, enforces path safety, sanitizes model output, and restricts writes to allowed files.

4. Cost Guard enforces hard limits. Per-call caps, daily caps, tier constraints.

5. Results are logged. Success rate and cost per success drive routing decisions.

Humans approve routing changes. Nothing updates itself silently.

## Quick start

```bash
git clone https://github.com/bigbirdreturns/tier-bench.git && cd tier-bench
bash setup.sh
```

Set at least one provider key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...    # or
export OPENAI_API_KEY=sk-...           # or
export GEMINI_API_KEY=...              # or start Ollama for $0 local models
```

Run:

```bash
python orchestrator.py --dry-run "Add authentication"     # estimate cost, no API calls
python orchestrator.py --benchmark T0                      # run T0 tasks (~$0.01)
python orchestrator.py --benchmark all                     # run all tiers
python scripts/compute_metrics.py                          # view routing table
python scripts/generate_cheatsheet.py --results harness_results.jsonl  # HTML reference
```

## Adding models

Edit `models.json`. Every model is one entry:

```json
"my-quantized-thing": {
  "provider": "ollama",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T1"
}
```

`tier_ceiling` is your hypothesis. The benchmark proves or disproves it.

Supported providers: `anthropic`, `openai`, `deepseek`, `mistral`, `google`, `ollama`, `openai-compat`.

For HuggingFace models via Ollama: `ollama pull hf.co/username/model-GGUF`, add the entry, run the benchmark.

For any OpenAI-compatible endpoint (LMStudio, vLLM, text-generation-inference):

```json
"my-vllm-model": {
  "provider": "openai-compat",
  "base_url": "http://localhost:8000/v1",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T2"
}
```

## Adding tasks

See [CONTRIBUTING.md](CONTRIBUTING.md). Add a fixture directory and a JSON manifest. Run `python scripts/validate_task.py` to verify. If it passes, it will not break the harness. No Python changes needed.

## Cost controls

| Layer | What it does | Default |
|-------|-------------|---------|
| Provider billing cap | Hard limit in your provider console | Set this yourself |
| Daily spend limit | CostGuard refuses all calls after this | $10.00 |
| Per-call limit | Refuses any single expensive call | $1.00 |

Running the full T0-T3 benchmark costs roughly $0.15. Weekly automation runs about $0.60/month.

## What this is not

Tier Bench is not an agent framework, not an auto-refactor tool, not a prompt playground, and not a "just trust GPT-4" wrapper. It exists to make model selection boring, predictable, and cheap.

## Claude Code integration

Drop `CLAUDE.md` in your project root. Claude Code reads it automatically and self-routes: Haiku for formatting, Sonnet for debugging, Opus only for architecture. No Python harness needed.

## Status

This project is intentionally narrow in scope. If it cannot be measured deterministically, it is not benchmarked. That constraint is the feature.
