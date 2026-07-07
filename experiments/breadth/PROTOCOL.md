# Breadth-baseline protocol — map the model, harvest every token, escalate on evidence

You have a billing cascade that unlocks the big model (Fable / max) on an
escalating cost scale. You want to point a fresh Claude Code session (ultra
effort) at this repo and get the **best possible baseline** — the model's full
breadth mapped — with two guarantees:

1. **Every token is harvested** — no run silently loses telemetry.
2. **Every cost escalation is a true need** — mapped from a measured ceiling, not
   trial-and-error.

This is the procedure and the two tools that enforce it.

## The one distinction that makes escalation honest

> One miss is noise. **K-of-K** misses is a ceiling.

You never escalate a task because a run "felt weak." You escalate only when the
current rung fails it **reproducibly** (K independent trials, all fail) *and* the
next rung clears it **reproducibly** (K trials, all pass). Anything in between is
`unstable` — the honest verdict is *run more trials*, not *pay more*. That single
rule is the whole guardrail against trial-and-error escalation.

## The ladder (run in this order)

**Stage 0 — Instrument before you spend.** Every model call appends one row to the
token ledger (`ledger.py`): account, model, tier, task, phase, effort, tokens
in/out/cache, cost, latency, outcome, trial. Then `reconcile()` the ledger against
the account's billed usage. **If it doesn't reconcile within tolerance, stop** — a
call went unlogged, a buffalo escaped, and every downstream number is contaminated
until it balances. (This is the exact failure that dropped `results.jsonl` here
once; the ledger + reconciliation exist so it can't happen silently.)

**Stage 1 — Cheap + harness on everything.** Run the whole task set at the cheapest
tier *with* the capability harness (the lens sweep / empirical search). Record
cost-per-success. This is the floor, and — per `experiments/tier-uplift` — it
clears most operational work.

**Stage 2 — Measure ceilings, K trials each.** For every task, run K trials at its
current tier. `classify()` labels each (task, tier): `clears` (passes all K),
`wall` (fails all K), or `unstable` (mixed → needs more trials).

**Stage 3 — Escalate only walls, one rung at a time.** For a task that is a `wall`
at tier T, probe T+1 (K trials). If T+1 `clears`, the escalation is **justified**
and recorded with its evidence (`0/K at T → K/K at T+1`). If T+1 is also a `wall`,
the ceiling is *not* a tier ceiling — it is a harness gap or a genuinely
unverifiable task; escalating further (paying for max) is unjustified until you know
which. Never jump straight to max on a hunch.

**Stage 4 — The baseline is the frontier, not the ceiling.** For each task, the
baseline tier is the **cheapest tier that clears it reliably**. Sum the per-task
minimum cost and you have the best baseline: the model's full breadth mapped at the
true floor price, every escalation backed by a K/K wall you can point at.

## What the tools give you

```bash
# harvest + prove nothing was lost
python experiments/breadth/ledger.py runs.jsonl --billed 12.40 --account acct-B

# the breadth map: cheapest-that-clears per task, justified escalations, waste avoided
python experiments/breadth/escalate.py runs_trials.jsonl \
    --tiers cheap,mid,frontier,max --cost cheap=0.03,mid=0.13,frontier=0.20,max=0.63
```

`escalate.py` emits, per task: `min_sufficient_tier`, `cost_at_min`,
`cost_if_max_everywhere`, `waste_avoided`, and the raw K/K measurements; plus the
list of **justified** escalations (with evidence), any **unjustified** ones
(`unstable` — go get more trials), a `baseline_cost_usd` (cheapest-that-clears,
summed) and `naive_max_everywhere_usd` (what blindly running max would cost). On the
illustrative set in `example_trials.jsonl` that gap is **$0.29 vs $3.15** — the
breadth map is the difference between paying for the ceiling and paying for the need.

## Why this maps the *full breadth* (and not just the ceiling)

Running max everywhere maps the ceiling but tells you nothing about the frontier —
you learn where the model tops out, not where each capability *starts being free*.
Running cheap everywhere never sees the ceiling. The ladder does both: it walks each
task up from the floor until it clears, so the map records, per capability, the
exact rung where it becomes reliable. That frontier — not the ceiling — is the
baseline worth having, and it is the only one that tells you where your Fable budget
is a true need versus waste.

## Honesty seams

- **No conclusion before reconciliation.** A run whose ledger doesn't match the bill
  is discarded, not interpreted.
- **K, stated.** Report K (trials per cell). A ceiling from K=1 is not a ceiling.
- **Unstable ≠ escalate.** Mixed results buy more trials, never a higher tier.
- **Escalations carry evidence.** Every paid jump records the K/K wall that forced
  it, so "why did we pay for Fable here?" always has a data answer.
