# PROJECT STATUS — Feb 13, 2026

## What This Is

A config-driven system that measures which LLM models can handle which coding tasks, so you route cheap models to easy work and save money.

Two modes:
- **Benchmark:** Test models against deterministic tasks → get empirical routing data
- **Orchestrate:** Decompose plain-English requests → auto-route subtasks to cheapest capable model

## What's Complete

### 12 Deterministic Tasks (T0–T3)

| Tier | Tasks | What They Test | Validators |
|------|-------|---------------|------------|
| T0 | 3 | Format, lint, rename — must not change behavior | compile, ruff, functional equivalence |
| T1 | 3 | Implement from spec with edge cases | compile, tests |
| T2 | 3 | Multi-file bugs, API integration | compile, tests, diff bounds |
| T3 | 3 | SQL injection fix, god function refactor, cross-module inverted logic | compile, tests, AST structural checks |

### Config-Driven Model Registry

`models.json` — add any model without editing Python:
```json
"my-local-model": {
  "provider": "ollama",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T2"
}
```

Routing table auto-generated from tier ceilings, sorted cheapest first.

### Extensible Task System

Anyone can add tasks without touching harness code:
1. Add a fixture directory to `fixtures/`
2. Add a JSON manifest to `tasks/`
3. Run `python scripts/validate_task.py` — if it passes, it won't break anything

See `CONTRIBUTING.md` for the full contract.

### 7 Providers
Anthropic, OpenAI, Mistral, DeepSeek, Google, Ollama, OpenAI-compatible endpoints (LMStudio, vLLM, etc.)

### Safety
- Budget caps (per-call and daily)
- Path traversal protection
- Response sanitization (rejects prose, accepts only code)
- Functional equivalence testing for T0
- Full audit trail (every API call logged)

### Tooling
- `orchestrator.py --benchmark T0` — run harness
- `orchestrator.py --dry-run "task"` — estimate cost, no API calls
- `orchestrator.py "task"` — decompose and execute
- `scripts/compute_metrics.py` — aggregate results
- `scripts/generate_cheatsheet.py` — HTML cost/capability reference
- `scripts/validate_task.py` — validate contributed tasks
- `setup.sh` — one-command install

## How Tiers Are Set

Two methodologies that meet in the middle.

**Bottom-up (T0–T3):** Deterministic tests prove the floor. A model either passes or it doesn't. The `tier_ceiling` in `models.json` is a hypothesis until the benchmark confirms it.

**Top-down (T4–T5):** Assigned based on frontier positioning. These tiers involve planning and architecture where "correct" is a judgment call. You evaluate the output yourself, same as you would a staff engineer.

T3 is where the methodologies overlap — the tasks require real judgment (find a security bug, decide how to refactor) but the validation is still deterministic (did the injection test pass, did the AST check find enough extracted functions).

## What's Not Built

- **T4–T5 tasks** — described in README, deferred by design
- **Docker sandboxing** — executes on host, fine for local use
- **Arbiter system** — for eventual subjective evaluation
- **Zero benchmark results** — nobody has run it against a real API yet

## Cost

- Full T0–T3 benchmark run: ~$0.15
- Weekly automation: ~$0.60/month
- Local models via Ollama: $0
