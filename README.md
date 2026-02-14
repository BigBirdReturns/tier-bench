# Model Capability Harness

Stop paying senior-engineer rates for intern work.

This system figures out which LLM models can handle which complexity of coding task, so you route cheap models to easy work and only pay for expensive models when you actually need them.

**📊 [Live Pricing & Capability Cheatsheet](https://bigbirdreturns.github.io/model-capability-harness/)**

## The Problem

Developers default to frontier models for everything. Sorting imports with Opus is like hiring a principal engineer to alphabetize a filing cabinet. The industry evaluates models on vibes. This evaluates them on deterministic pass/fail tests against real coding tasks.

## From Zip to Running

```bash
unzip model_capability_harness.zip && cd model_capability_harness
bash setup.sh
export ANTHROPIC_API_KEY=sk-ant-...  # or any supported provider
python orchestrator.py --dry-run "Add user authentication"  # free, no API calls
python orchestrator.py --benchmark T0  # costs ~$0.01
python scripts/compute_metrics.py  # see your routing table
python scripts/generate_cheatsheet.py --results harness_results.jsonl  # HTML reference
```

## How Tier Ceilings Are Set

This is the most important section. There are two different methodologies at work, and they meet in the middle.

### Bottom-Up: T0–T3 (Deterministic Testing)

Tiers 0 through 3 are backed by **12 deterministic test tasks** with objective pass/fail criteria. No vibes. The harness runs each task against every model at that tier ceiling, and either the output compiles and passes tests, or it doesn't.

| Tier | What It Tests | # Tasks | Validators |
|------|--------------|---------|------------|
| T0 — Clerical | Format, lint, rename. Must preserve runtime behavior exactly. | 3 | compile, ruff imports, functional equivalence |
| T1 — Junior | Implement from a docstring spec. Edge cases included. | 3 | compile, test pass |
| T2 — Mid | Fix bugs, implement clients, coordinate across files. | 3 | compile, test pass, diff bounds |
| T3 — Senior | Security audit (find SQL injection), refactor god functions, debug cross-module bugs with inverted logic. | 3 | compile, test pass, structural checks (AST) |

**Why this works:** T0 tasks are deliberately boring — a model that "helpfully" refactors while formatting fails the functional equivalence check. T1 specs have edge cases (café → caf, multiple hyphens) that weak models miss. T2 tasks require reading across files. T3 tasks require judgment — recognizing a vulnerability, deciding how to decompose a function, tracing a bug through two modules with inverted comparison logic.

**What it proves:** When the harness says a model passes T2, that model actually demonstrated it can fix a division-by-zero, implement an HTTP client, and coordinate a multi-file patch. That's not a claim — it's a test result.

### Top-Down: T4–T5 (Assumed From Frontier Position)

Tiers 4 and 5 have **no automated tests.** These tiers involve planning, architecture, and decomposition — tasks where "correct" is a judgment call, not a compiler check.

| Tier | What It Means | How Ceiling Is Set |
|------|--------------|-------------------|
| T4 — Staff | Decompose vague requests into plans, design interfaces | Assigned to models priced/positioned as frontier reasoning models |
| T5 — Principal | Architecture tradeoffs, long-horizon decisions | Assigned to the most capable models available |

**Why this is honest:** You don't give a principal engineer a multiple-choice test. You look at their work and decide if it was worth the rate. T4/T5 models are expensive ($5–$25/M output tokens). If you're paying that much, you're going to evaluate the output yourself. The harness doesn't pretend to automate that judgment.

**Why this still saves money:** The value isn't in proving Opus can think. The value is in proving that Haiku can handle T0 and T1 — which means 80% of your coding tasks go to a model that costs 95% less. T4/T5 gets touched once or twice a day for planning.

### The Middle: Future T4 Testing

T4 is the most testable of the upper tiers. The orchestrator's planner is a T4 task — give it a request and a repo, get back a JSON plan. You could test: does the plan have valid file paths? Are tier assignments reasonable? Do the subtasks actually execute when fed back through the harness? This is buildable. It just isn't built yet.

## Adding Your Own Models

Edit `models.json`. Every model is one entry:

```json
"my-quantized-thing": {
  "provider": "ollama",
  "input_per_1M": 0,
  "output_per_1M": 0,
  "tier_ceiling": "T1"
}
```

The `tier_ceiling` is your hypothesis. The benchmark proves or disproves it.

Supported providers: `anthropic`, `openai`, `deepseek`, `mistral`, `google`, `ollama`, `openai-compat`.

For HuggingFace models: `ollama pull hf.co/username/model-GGUF`, add entry, run benchmark.

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

## Cost Controls

| Layer | What It Does | Default |
|-------|-------------|---------|
| Provider billing cap | Hard limit in your provider console | Set this yourself |
| Daily spend limit | CostGuard refuses all calls after this | $10.00 |
| Per-call limit | Refuses any single expensive call | $1.00 |

## Commands

```bash
python orchestrator.py "your task here"           # decompose, route, execute
python orchestrator.py --benchmark T0              # test models against T0 tasks
python orchestrator.py --benchmark all             # test all tiers
python orchestrator.py --dry-run "your task"       # estimate cost, no API calls
python scripts/compute_metrics.py                  # view benchmark results
python scripts/generate_cheatsheet.py              # generate HTML reference
python scripts/generate_cheatsheet.py --results harness_results.jsonl  # with benchmark data
```

## Claude Code Integration

Drop `CLAUDE.md` in your project root. Claude Code reads it automatically and self-routes: Haiku for formatting, Sonnet for debugging, Opus only for architecture. No Python harness needed for this — it works today.
