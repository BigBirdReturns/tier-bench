# Self-run breadth RUNBOOK — Sonnet prepares, Fable maps itself, you decide access

The workflow you described, made concrete. One Claude Code session, tier-bench
only. Sonnet sets everything up and lays the cheap floor; you toggle Fable (ultra);
Fable runs the tests on itself, cascading its own effort; when it nears the quota
limit it checkpoints and hands you one honest decision. Designed right, you never
escalate access.

## No API key required

This run does **not** use `ANTHROPIC_API_KEY` or `orchestrator.py`'s real-call path.
The model that attempts each task is **the Claude Code session itself** (Sonnet in
Phase 1, Fable in Phase 2) — either solving each task inline and grading with the
deterministic graders, or spawning a subagent (the Agent tool) as the "cheap tier"
worker, exactly as `experiments/tier-uplift` did with real model instances and no
keys. `orchestrator.py --dry-run` and the graders work keyless; only a real
`orchestrator.py` benchmark sweep needs an exported key, and that is a *separate*
flow from this runbook. If the session says it's blocked on a missing key, it has
defaulted to the orchestrator path — point it back here.

## The two knobs, in order

1. **EFFORT** (`low → medium → high → xhigh → max`) — the cheap knob, varied within
   Fable. Cascade this first. It's most of the capability range and costs you
   nothing but tokens you already have access to.
2. **ACCESS** (your billing cascade: first → pro → max) — the expensive knob. Not
   automatic, not a rung. You only reach for it when the map still has **residual you
   can't finish inside your current quota** — a *quota* decision, never a *difficulty*
   one. (A task that walls at `fable@max` is a capability ceiling; more access buys
   nothing for it.)

## Phase 1 — Sonnet prepares + lays the floor

Start the session in **Sonnet** and paste:

> You are preparing a breadth-mapping run of this repo's own task set, to be
> executed later by Claude Fable. Do the prep only — do NOT switch models.
> 1. Assemble the task set: the graded tasks under `tasks/`/`fixtures/` plus the
>    `experiments/tier-uplift` subjects. Write the list to
>    `experiments/breadth/run/tasks.txt`.
> 2. Lay the cheap floor. For each task, K=3 times: spawn a **cheap-model subagent**
>    (the Agent tool, model `haiku`) to *solve* the task — produce the target file
>    per the manifest. Then **grade deterministically**: run the task's own
>    `run_command` / `harness.validators.validate_all` on the produced file (pass =
>    exit 0 / validators pass). Log every attempt to
>    `experiments/breadth/run/ledger.jsonl` via `experiments/breadth/ledger.py`
>    (`tier="claude-haiku-4-5@harness"`, tokens/cost from the subagent usage).
>    NOTE: the harness (`capability_harness`) *reviews code* — it is an **augmentation
>    for bug-finding/review tasks** (give the subagent the lens findings before it
>    fixes), **not** the solver, and it does nothing for implement-from-spec tasks.
>    The grade→log→map spine is proven keyless by `experiments/breadth/smoke.py`;
>    the only added piece here is the subagent doing the solve.
> 3. The **residual** = tasks the cheap floor did NOT clear reliably (K=3).
>    Write it to `experiments/breadth/run/residual.txt` — this is all Fable needs to
>    touch, which conserves Fable quota for where it matters.
> 4. Write `experiments/breadth/run/PLAN.md`: the residual queue, the effort ladder
>    from `rungs.ladder()`, K=3, and the quota you're giving this run. Then STOP and
>    tell me to switch to Fable.

Sonnet clearing the easy floor is the whole reason Fable's limited quota lasts:
Fable spends nothing re-solving what the cheap model + harness already nails.

## Phase 2 — you toggle Fable (ultra), Fable maps itself

Switch the session to **Fable at max effort** and paste:

> Execute `experiments/breadth/run/PLAN.md`. For each task in `residual.txt`, walk
> the effort ladder from the BOTTOM: `fable@low` first, K=3 trials, grading each.
> - **clears** (3/3): stop — that's the task's minimum sufficient rung, recorded.
> - **wall** (0/3): step up one effort and repeat.
> - **unstable** (1–2/3): run 2 more trials before deciding; never step up on noise.
> Also run 3 known-easy tasks at `fable@low` as calibration (confirm the floor).
> Log EVERY call to `ledger.jsonl` (tokens, cost, effort, outcome, trial). After
> each task, refresh the map: `python experiments/breadth/escalate.py run/ledger.jsonl`
> (use `rungs.as_escalate_args`). When `limit.budget_status` says `approaching`
> (≥80% of quota), STOP and print the `decision_packet` — do not silently continue.

Yes — **Fable runs the lower difficulties too**, at `low` effort, and that's the
point: you can't know a task is "free for Fable" without seeing Fable clear it
cheaply. Running the residual bottom-up traces the full capability × effort curve
instead of one max-effort point — a far more robust map, at the floor price.

## Phase 3 — the limit handler → your one decision

When Fable nears the quota, it stops and prints the decision packet
(`experiments/breadth/limit.py`). It separates the two things that look alike:

- **Unmapped residual** — tasks not yet walked to a clear or a max-effort wall. If
  finishing them won't fit remaining quota → **ESCALATE ACCESS** is worth it (a quota
  decision: more access = more quota to finish the map).
- **Capability ceilings** — tasks that walled at `fable@max`. **Access won't help**;
  route them to the harness (let Fable *search*, not derive) or mark them genuinely
  hard / unverifiable.

If there's no unmapped residual, the recommendation is **DO NOT ESCALATE** — the map
is complete within current access and you already have the best baseline. That's the
"hopefully not, if designed right" outcome, and the Sonnet floor + effort cascade are
what make it the likely one.

## The baseline you walk away with

For every task, the **cheapest rung that clears it reliably** — cheap+harness where
possible, the lowest Fable effort where not, `fable@max` only where truly needed.
Sum it and that's your project baseline: full breadth mapped, every escalation (of
effort *or* access) backed by a `0/K → K/K` receipt in the ledger, and every token
reconciled against the bill (`ledger.reconcile`). Not the ceiling — the frontier.

## Commands

```bash
python experiments/breadth/rungs.py                         # print the ladder + escalate args
python experiments/breadth/ledger.py run/ledger.jsonl --billed <acct_usd>   # harvest + reconcile
python experiments/breadth/escalate.py run/ledger.jsonl --tiers <ladder> --cost <costs>   # the map
python experiments/breadth/limit.py run/ledger.jsonl --breadth map.json \
    --quota-usd <Q> --top-rung claude-fable-5@max          # budget + decision packet
```
