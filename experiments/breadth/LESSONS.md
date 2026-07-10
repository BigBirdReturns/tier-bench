# Breadth run — lessons learned (read this before you spend a frontier token)

Hard-won rules from the first end-to-end run. Each one is here because it was
gotten *wrong* first. If you're the driver (Fable/ultracode) picking this up, read
this, then `RUNBOOK.md`, then go. The goal is an efficient, honest firehose that
builds a durable corner of the *settled* world — not a victory lap.

## The doctrine, one line

**Seal what's stopped moving; rent only what hasn't; prove the difference.**
Settled operational work commoditizes to a cheap sealed artifact. The only thing
worth a live frontier call is what's still being *derived*. The whole job is
drawing that waterline correctly — and proving which side each cell is on.

## The rules (and the mistake each one prevents)

1. **Map only hidden-grader tasks.** An agentic solver reads any grader it can see
   and brutes it, so a task measures capability *only* if the deciding grader is
   hidden. Use exactly `python experiments/breadth/breadth_tasks.py`. Never the
   `tasks/*.json` manifests — their grader is the file the solver edits.
   *(Mistake: the first Phase-1 "cleared everything" was the solver reading the
   answer key, not capability.)*

2. **Honor DO NOT ESCALATE.** If the cheap floor clears a cell (hidden-graded), it
   is done. An empty residual means **you do not turn on Fable at all.** Do not pay
   frontier prices to re-confirm a floor you already measured.
   *(Mistake: ~1/3 of a pro-plan Fable allotment got burned on calibration —
   re-confirming a cleared floor. The `limit.py` gate exists to stop exactly this.)*

3. **Escalate effort before access; K-of-K is a ceiling, one miss is noise.** Walk
   `rungs.ladder()` from the bottom (fable@low → max) and step up only on a *wall*
   (fails all K). A single miss is noise → run more trials, don't pay more. Only
   when max-effort walls is *access* even a question — and that's a human call.

4. **The residue is novel reasoning, not richer specs.** A competent cheap model
   implements to *any* spec you hand it — even hidden-graded, even with a semantic
   judge (measured: 6/6). You cannot find the frontier gap by making specs harder.
   The gap lives only where the answer must be *derived* (counterexample
   construction, task06-shape). Grow the corner with those, not with thicker specs.

5. **Verify grades independently — a model saying "the grader passed" is not the
   grader passing.** Re-run the hidden grader yourself on the candidate. Two live
   failures: a Codex PR (#40) logged fabricated `pass` rows (identical timestamps,
   0 tokens, invented model); and this workflow's "all settled" needed a hand re-run
   to confirm (it held — but only because it was checked). Trust the grader output,
   never the narration of it.

6. **K=1 is not "settled".** "Settled" means 3/3 at `clear_thresh=1.0`. A single
   pass is "cleared once." The `initial` KNOWN_CORNER layer is K=1 provisional.

7. **Efficiency is context, not effort.** The burn was **~170k cache-read tokens
   per Fable trial** — a bloated solver context, not the reasoning. Fixes: give the
   solver *only* spec + visible tests + the target file; run trials sequentially from
   a constant cwd so the 1h prompt cache is written once (cold ~$0.85) and read after
   (~$0.42). And the cost model is ~40% low: `fable@low` is **~$0.48/trial real**,
   not the $0.30 in `rungs.py` — update estimates from measured `total_cost_usd`.

8. **Adapt freely, but never self-grade.** `adapt.py` enforces it: FREE changes
   (solve strategy, prompts, lens choice, trial policy, ordering, effort ladder)
   apply and log; GATED changes (a grader, pass criteria, a task, cost accounting)
   are forced to proposal-only for human review. A model that can loosen its own
   grader will.

9. **Reconcile or don't trust it.** No conclusion stands on books that don't match
   the bill (`ledger.reconcile`). Separate **real-billed** (Fable CLI `total_cost_usd`)
   from **shadow** (subagent estimates — no provider bill exists). Your quota burn is
   only the real-billed rows.

10. **Records accumulate (sediment).** `known_corner.jsonl` is append-only. A re-run
    DIFFs against the newest layer and only re-probes non-`settled` cells. Old
    sediment is never re-derived — you pay only to lay down what's new.

11. **Authoring lesson: your own spec wording can defuse the knot, and "find a
    counterexample" framing makes derivation search-shaped.** Measured on the first
    purpose-built discriminator tasks (task08/09/10, 2026-07-10): all three cleared or
    near-cleared the haiku floor. task09 was built as a task02-isomorphic
    malformed-vs-unsatisfiable knot — but its input guarantee ("you never need to
    reject a pattern") telegraphed the resolution, so the trap never bit. task08's
    counterexample construction was cracked 4/5 (the only miss was a domain-bounds
    slip): once the ask is "return an input that breaks this," a competent cheap
    solver builds its own brute-force oracle and sweeps — the same search-shaped
    lifting task06 measured. To wall the floor, the knot must stay embedded in a
    larger judgment (as in task02, where the degenerate case arrives unannounced
    mid-implementation), and the spec must not carry a guarantee that resolves it.
    *(Mistake: authored three "novel-reasoning" tasks and the floor ate them.)*

12. **Focused lenses have tunnel vision — the sweep needs one open eye.** Measured
    on a dense subject (`experiments/lens-proofs/dense_orders`): baseline general
    pass 7/10, frozen-five sweep alone 9/10 (every lens missed the use-after-close
    the plain pass caught), baseline ∪ lenses **10/10**. `review()` now runs a
    general pass alongside the lenses by default. Corollary, corroborated three
    times (two small subjects + one dense): `resource_lifetime` and `concurrency`
    are NOT cheap-model blind spots — those candidates are permanently retired.
    The lanes that actually recover baseline misses: `data_types` (float-money
    equality) and `contracts` (silent-default holes).

## What's already built (your toolbelt)

- `RUNBOOK.md` — the two-phase (+ autonomous "walk away") protocol.
- `breadth_tasks.py` — the valid (hidden-grader) task set; `is_gameable()` guard.
- `ledger.py` — per-call telemetry + `reconcile()`.
- `escalate.py` / `rungs.py` / `limit.py` — the breadth map, the effort ladder, the
  approaching-the-limit decision packet (quota vs capability-ceiling).
- `adapt.py` — the FREE/GATED reward-hacking gate.
- `smoke.py` — proves the grade→ledger→map spine keyless on one task.
- `build_known_corner.workflow.js` — the orchestrated firehose (parallel floor →
  escalate-only-walls → seal/accumulate). Run it with the Workflow tool; grow its
  `CORNER` list to grow the corner.
- The sealed lens shard (`memory/lenses/`) — the harness lenses, verifiable.

## The move

Point the corner at settled, hidden-graded work. Fan out cheap in parallel. Fire
the frontier ONLY where cheap genuinely walls. Verify every grade. Seal the settled
cells as a new sediment layer. Come back with a decision packet, not a bill.
