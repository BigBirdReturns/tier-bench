# Tier Bench

Tier Bench is an empirical benchmarking system for LLM routing. It measures which models actually succeed at different task tiers and what they cost per successful outcome, then feeds that data into a cost-guarded router.

This replaces vibe-based model selection with operational data.

**Succession:** [HANDOFF.md](HANDOFF.md) is the 30-year document — mission, constitution, data contracts, and takeover protocol for whichever model or human drives this next. Keep it current.

**[Live site — how it works, test your own workflow, compare your results](https://bigbirdreturns.github.io/tier-bench/)** · [pricing cheatsheet](https://bigbirdreturns.github.io/tier-bench/cheatsheet.html)

## Beyond the router — the capability program

Reproducible work built on top of the benchmark (all on `main`):

- **[Capability harness](capability_harness/README.md)** — lift a cheap model to the tier above on operational tasks, any provider. `pip install .`, then `capability-harness review mycode.py`.
- **[AXM Estate Lab](estate_lab/README.md)** — exercise cross-project semantic actions, authority, fallback routing, deterministic state, device substitutions, project probes, and fault recovery with inspectable receipts.
- **[The living lens shard](memory/lenses/README.md)** — the lens registry sealed as a signed, tamper-evident AXM Genesis shard (`axm-verify` PASS; one-byte tamper fails closed).
- **[Burden discipline](docs/burden-discipline.md)** — the prosecutor-readable closure-packet rule: every accepted, routed, verified, paid, safe, or ready claim must name the burden, verifier, gap, and failure default.
- **[Findings page](https://bigbirdreturns.github.io/tier-bench/uplift.html)** — the operational-moat write-up and the "workspace inside/outside" frame.
- **[Breadth self-run RUNBOOK](experiments/breadth/RUNBOOK.md)** — Sonnet-prepares / Fable-maps-itself, with token harvesting (`ledger.py`) and evidence-driven, effort-first escalation (`escalate.py`, `rungs.py`, `limit.py`). **Runs keyless via Claude Code subagents** — see the runbook.

## The problem

Most AI tooling does this:

1. Pick a "best" model by reputation
2. Route everything to it
3. Hope the bill does not explode

That approach fails because cheap models are good at many tasks, expensive models are only needed for a few, nobody measures success rate per task tier, and token cost alone is meaningless without success probability.

Routing without measurement burns money.

For real repository work, [`tier run`](docs/tier-runner.md) is the fail-closed
daily entrypoint: immutable operator acceptance, a disposable worktree, and a
patch plus receipts instead of a silent merge.

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
| T4 | Planning, decomposition. | 1 | JSON plan lint (visible) + hidden semantic judge |
| T5 | Architectural judgment. | 0 | Not benchmarked. Human review. |

Tier Bench is explicit about what it measures and what it does not.

T0 through T3 have 13 deterministic tasks with objective pass/fail, and T4 has its first (plan validity: visible schema lint + hidden semantic judge). T5 ceilings are assigned by frontier positioning. The README does not pretend otherwise.

## Current measured finding (the waterline)

Tier Bench measures **the cheapest verified execution path** for hidden-graded
tasks. As of the first sealed sediment layers (2026-07-08):

- **Spec-following tasks are settled at the cheap floor** in the measured set —
  hidden-graded, K=3, T0 through T4.
- **The first measured model separation is a judgment-boundary residue, not a
  task tier**: task02's escape-inside-class rule cracks haiku (3/5) and clears
  at sonnet-5@low (hidden 10681/10681 ×3, ~$0.23/trial real-billed).
- **The router should key on settled-vs-derived work, not declared tier
  ceiling.** Ask the instrument: `python experiments/breadth/waterline.py
  --task <task_id>` — settled routes cheap, residue is named and priced,
  missing evidence says missing.

**Measured update (2026-07-08):** with hidden grading (the solver never sees
the deciding tests), the cheapest current model clears T0–T4 spec-following at
3/3 — the difficulty ladder no longer separates 2026 models; the axis that
does is settled (spec-following) vs. derived (judgment/counterexample) work.
The original hypotheses are scored against the data in
[HYPOTHESES.md](HYPOTHESES.md); the measured frontier residue so far is one
nameable judgment edge (`experiments/breadth/run/task02_edge_family.md`).

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

## Frontier diff & replication (driver / hands)

When a new frontier model ships, the question is never "is it good" — it is
**what does it measurably give you over what you already have, and how much of
that can a cheaper composition give back?** Tier Bench answers both from the
same results file, and the design is deliberately model-agnostic: models,
roles, and composition strategies are registry *data* (`models.json`), so the
workflow survives every model generation that will ship over the life of this
repo.

**Roles.** `models.json` has a `roles` section. The `driver` is the model that
plans, verifies, and repairs — it spends judgment tokens, never bulk tokens.
The orchestrator uses `roles.driver` as its planner (override per-run with
`--driver` or `TIER_BENCH_DRIVER`); execution always auto-routes to the
cheapest capable model. Swap the driver by editing one line of JSON.

**Composite candidates.** The `composites` section defines compositions that
the benchmark runs as first-class rows, so "a cheap model plus a harness
replicates the frontier model" becomes a measured claim with a price on it:

| Strategy | What it does | What it proves |
|---|---|---|
| `cascade` | Try members cheapest-first; first validated pass wins | An escalation ladder prices the average call down |
| `best_of_n` | Resample one member; task validators select | Verification buys back single-shot quality |
| `driver_repair` | Cheap "hands" model attempts; on failure the **driver** gets the failed output + validator report and produces the repair | The frontier model is worth paying for judgment, not typing |

Composites are priced by **every call they make, failures included** — and a
failed attempt is never wasted: `driver_repair` feeds it to the driver as
evidence.

**The diff report.** After a benchmark run:

```bash
python orchestrator.py --benchmark all
python scripts/diff_report.py                 # target defaults to roles.driver
python scripts/diff_report.py --json          # machine-readable
```

Per tier it renders one of: `REPLICATED — <model> matches at N× lower
cost-per-success`, `FRONTIER EDGE — nothing benchmarked matches; this is what
you pay for`, or `TARGET FAILS this tier`. It closes with the target's
measured ceiling vs its registry claim, and names the tiers that were never
deterministically measured — capability above the ruler is a claim, not a
measurement, and the report refuses to speak about it.

Model-side safety refusals are logged distinctly (`model_refusal`) and count
as failed attempts: refusal risk is part of a model's real-world price.

## Teaching the driver role (distillation)

Being the driver is a method, not a model (`driver/README.md`). Every
`driver_repair` repair is imitation evidence: (task, failed hands output,
validator report) -> (driver's fix, passed?). Validation already grades each
one — pass or fail, no self-report — so the passing tuples are a curriculum,
not a guess. Collecting enough of them lets a cheaper model learn the move by
example first, then by fine-tuning on the same corpus: distillation of
judgment, not weights.

```bash
python orchestrator.py --benchmark all         # driver_repair composites auto-capture to driver_traces.jsonl
python scripts/distill.py                      # emit the curriculum: driver/README.md + passed exemplars
```

See `driver/README.md` for the full teach loop and the graduation test: set
the apprentice as `--driver`, benchmark it, and check
`scripts/diff_report.py --target <apprentice>` — it has replicated the driver
when its cost-per-success on the role matches the frontier's.

## Rig report — laptop to server farm

```bash
python scripts/rig_report.py                  # probe THIS machine
python scripts/rig_report.py --vram-gb 24     # "what if I had a 24 GB GPU"
python scripts/rig_report.py --emit-config    # paste-ready registry fragment
```

Probes your hardware (RAM, cores, NVIDIA/AMD GPUs, Apple-silicon unified
memory — no dependencies) and maps it against the registry:

- **What you can already run at $0** — which local models fit, using the
  sizing heuristics the local-inference projects publish (Q4 ≈ 0.6 GB per
  B params + KV/runtime overhead), and the task tier that covers.
- **Commodity vs frontier, per tier** — which tiers your rig or a
  pennies-per-call API model already holds, and which genuinely need
  frontier pricing. A large share of "frontier" usage is commodity-tier
  work at a 10-50× markup; this section shows exactly where that line sits
  on *your* machine. Verdicts say `measured` when backed by benchmark rows
  and `hypothesis` when not — the report never dresses up a guess.
- **Upgrade paths** — the next memory rungs (described as memory classes,
  not vendor SKUs, so the ladder stays true as hardware churns), what each
  rung unlocks, and the no-hardware alternative: cheap API hands +
  composites, with frontier spend reserved for the driver.

`--emit-config` prints the `ollama pull` commands for what fits plus a
ready-to-merge `driver_repair` composite that uses your best local model as
hands under the configured driver. Model parameter counts live in
`models.json` (`params_B`) — add local models there and the rig math follows.

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
