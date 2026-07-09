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
> 1. Assemble the **breadth-valid** task set — ONLY tasks with a hidden grader the
>    solver never sees. Run `python experiments/breadth/breadth_tasks.py`; use exactly
>    what it lists (today: `task01_parse_duration`, `task02_wildcard`, `task06_select`
>    in `experiments/tier-uplift`). Write it to `experiments/breadth/run/tasks.txt`.
>    Do **NOT** use the `tasks/*.json` manifests or tier-uplift task03/04/05/07 — the
>    solver can see those graders, so an agentic solver reads the answer key and every
>    task "clears" for free (that saturation is an artifact, not capability).
> 2. Lay the cheap floor. For each task, K=3 times: spawn a **cheap-model subagent**
>    (the Agent tool, model `haiku`) to *solve* it — give the subagent ONLY the
>    subject + spec + the weak `visible_tests.py`, **never the hidden grader**. Then
>    **score with the HIDDEN grader** (`hidden_tests.py` / `hidden_oracle.py` /
>    `grader.py`) — that produces the pass/fail, and it is never shown to the solver.
>    The daylight between visible and hidden is the whole signal. Log every attempt to
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

## Autonomous mode — kick off and walk away

You can start it and leave. The safe boundary: the run maps everything it can
**within your current access quota** and **parks at the limit with a decision
packet** — it never spends the next billing rung (pro/max) on its own. Access
escalation stays the one human gate. So "walk away" means you come back to either a
finished map, or a map complete-to-the-quota with one clear escalate-y/n question
waiting — never a surprise bill.

Kickoff prompt (paste once into the **Sonnet** session, then just toggle Fable when
it asks):

> Follow `experiments/breadth/RUNBOOK.md` autonomously. Run Phase 1 now — haiku
> subagents solve each task, the task's own grader scores it, log to
> `run/ledger.jsonl`, write `run/residual.txt` + `run/PLAN.md` — then stop and tell
> me to switch to Fable. After I switch you to Fable, run Phase 2 to ~80% of the
> quota in PLAN.md: walk each residual task bottom-up the effort ladder, K=3, logging
> every call. Adapt as you learn under `experiments/breadth/adapt.py` — improve HOW
> you solve/run freely, but NEVER change a grader or what counts as passing (propose
> those to `run/harness_log.jsonl` for me). At the limit, STOP and print the decision
> packet; do NOT escalate access — that's my call. Checkpoint the ledger and map so I
> can pick it up when I'm back.

## Adaptive harness — learn and adjust, never self-grade

Fable can think about the harness and change it as it learns, inside a bright line
that `experiments/breadth/adapt.py` **enforces in code** (not just asks for):

- **FREE** — apply immediately, just log it: solve strategy, prompt wording, which
  lenses to use, trial/retry policy within K, task ordering, tuning the effort
  ladder. These change *how the run works*, not what it measures.
- **GATED** — propose only, never self-apply: a task's grader, the pass criteria, a
  task definition, skipping a task, any ledger change that hides cost. `record()`
  forces `applied=False` on these regardless of what the model passes, and unknown
  targets fail safe to gated. They queue in `run/harness_log.jsonl` for your review.

Why the line is hard and not advisory: a model that can loosen its own grader to
pass **will**, and the map becomes a lie. That is the reward-hacking shape Anthropic's
J-lens work catches in the wild, and the reason this whole program keeps the
stochastic model off the scoring path. Fable gets to be smart about the harness; it
does not get to score itself. Review the queue anytime: `python experiments/breadth/adapt.py run/harness_log.jsonl`.

## Commands

```bash
python experiments/breadth/rungs.py                         # print the ladder + escalate args
python experiments/breadth/ledger.py run/ledger.jsonl --billed <acct_usd>   # harvest + reconcile
python experiments/breadth/escalate.py run/ledger.jsonl --tiers <ladder> --cost <costs>   # the map
python experiments/breadth/limit.py run/ledger.jsonl --breadth map.json \
    --quota-usd <Q> --top-rung claude-fable-5@max          # budget + decision packet
```

## Runnable tooling (committed — no session scratch required)

Phase 1/2 execute from `experiments/breadth/selfrun/`:

```bash
python experiments/breadth/selfrun/prep.py /tmp/breadth-scratch          # working copies, hidden files stripped, pre-edit baselines
# ...solver of your choice writes each trial's target file (session subagent, CLI, or pasted candidate)...
python experiments/breadth/selfrun/grade.py TASK_ID K --scratch /tmp/breadth-scratch [--model ... --tier ... --cost-usd ...]
python experiments/breadth/selfrun/effort_trial.py TASK_ID --scratch /tmp/breadth-scratch --effort low   # nested-CLI rung, exact tokens + real billed USD
```

Other lanes: `xprovider_run.py` (API providers), `subscription_run.py`
(subscription surfaces, candidates graded locally). All lanes append to the
same ledger schema; `breadth_tasks.py` says which tasks are breadth-valid.
