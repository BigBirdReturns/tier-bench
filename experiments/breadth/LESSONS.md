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

11b. **Corollary (measured 2026-07-13, authoring batch 2): embedded-unannounced is
    necessary but not sufficient.** Three rule-11-shaped tasks (anchor-vs-cascade,
    words-stated window endpoint, modified-following reversal) — each with verified
    naive-fails/reference-passes daylight, no defusing guarantees, knots arriving
    mid-implementation — ALL settled 3/3 at the haiku floor on first flooring
    (9/9 trials, hidden vectors included). A crisply stated rule gets implemented,
    however deep it is buried: the naive that drifts is a *careless* implementer,
    and the floor is not careless. The two knots that actually bit
    (task02 backslash-in-class, almanac lichun) share what these lack: the edge
    *feels contradictory* to the rule text, or the deciding quantity must be
    *derived* (bisection-class), not just applied. Author THOSE shapes next;
    stop authoring crisply-determined boundary rules and expecting them to wall.

12. **Focused lenses have tunnel vision — the sweep needs one open eye.** Measured
    on a dense subject (`experiments/lens-proofs/dense_orders`): baseline general
    pass 7/10, frozen-five sweep alone 9/10 (every lens missed the use-after-close
    the plain pass caught), baseline ∪ lenses **10/10**. `review()` now runs a
    general pass alongside the lenses by default. Corollary, corroborated three
    times (two small subjects + one dense): `resource_lifetime` and `concurrency`
    are NOT cheap-model blind spots — those candidates are permanently retired.
    The lanes that actually recover baseline misses: `data_types` (float-money
    equality) and `contracts` (silent-default holes).

13. **Smoke before cage.** Never build the golden conformance machinery —
    hash-bound freezes, ratification chains, fail-closed runners, custody
    receipts — before a cheap disposable run proves the runtime path actually
    runs. Bitten twice, same week. Sol-root activation v0.3: ~40 ceremony
    commits froze a 59-call schedule, then the FIRST executor call died because
    the CLI tool router silently downgraded `--sandbox workspace-write` to
    read-only (`invocation_equivalence_proven: false` — the only receipt check
    that required a live run was the one that failed; discovery cost 2 calls /
    204 output tokens, and could have been commit #1). ARC-D buffalo pilot:
    field contract + hash-bound packets built, then 3/3 live dispatches
    returned provider `systemError` with zero assistant bytes — and the frozen
    no-retry stopping rule converted an *infrastructure* failure into a
    permanent PARTIAL nobody may investigate. The procedure: before proposing
    any freeze/activation machinery for a live-dispatch lane, (a) list the
    properties only provable by running — sandbox writes, transport liveness,
    output-schema acceptance — and burn 1–2 disposable, non-frozen calls (or a
    $0 local CLI probe) proving them; (b) never let a no-retry rule designed
    for scientific integrity absorb infrastructure failures — classify
    infra-vs-observation BEFORE the stopping rule binds. Counter-example that
    proves the fix: the v0.4 repair (`run_v2.py` / `run_pilot.py`) verified CLI
    identity and ran a synthetic self-test green before any live access.
    Still-loaded instances as of 2026-07-17: TIER-PILOT (contract layer merged
    with 74 passing offline tests, zero model calls ever through the production
    shim, canary sequenced AFTER the byte freeze) and ARC-D-B2-CUSTODY-V2
    (activation will dispatch over the exact transport that just went 0-for-3).

    *Corroboration for rules 11/12 (2026-07-18, informal, N=1 per arm — see
    `races/README.md` for receipts):* four models solo (haiku→fable) plus an
    opus-driver/sonnet-hands DAG all went 12/12+9/9 hidden on the authoring-2/3
    discriminator knots. The capability gradient showed up ONLY as burn (speed,
    tool round-trips, verification depth), never as score — and haiku cleared
    three T3-labelled knots despite its registered T2 ceiling. The floor keeps
    eating crisply-stated knots; route crisp+deterministically-graded work
    cheap and spend the savings on graders.

14. **Verification is universal; self-verification is not. Buy the cheap
    model, keep the referee.** Measured across ~70 runs, 8 models, 2 vendors
    (races 1-6 + gauntlet waves, `races/`): every tier of both ladders solves
    everything deterministically gradeable (21/21 hard-shape, 42/42 cross-
    vendor, replicated); every tier certifies (21/21 adversarial certification
    with executing counterexamples). The ONLY crack found anywhere: haiku
    twice shipped broken graders while reporting them verified (distinct
    defect classes, hardened brief) - then went 3/3 catching the SAME defect
    class when placed in the referee role. The missing capability was never
    verification; it was reliably turning verification against one's own work
    while incentivized to finish. The frontier's measurable residue is surplus
    self-verification behavior, not exclusive reasoning - and the engineering
    answer is stronger than buying that behavior: EXTERNALIZE it. Separate
    author from referee; make acceptance executable. The doctrine: cheap
    models solve; cheap models certify; any tier authors behind a hardened
    gate; self-reports prove nothing; the referee - not the model - is the
    quality guarantee; frontier effort belongs in the referee, brief, and
    lesson pipeline. The boss round closed it: fable passed the same hostile
    machinery as everyone else, 66/66, no coronation, no exception - just the
    referee. The house wasn't haunted. It lacked smoke detectors.

15. **BOM-tolerant reads, or your referee invents a crack.** The 20-stage
    compounding chain reported spark's "first divergence at stage 10" - the
    program's only apparent solving failure. Adjudication (never trust the
    first number - lesson 14, pointed at your own harness): spark had written
    stage 10 via PowerShell's ConvertTo-Json, which prepends a UTF-8 BOM; the
    grader's plain `json.loads` choked and the runner scored it a divergence
    and halted. BOM-tolerant re-grade: 11/11 exact match, no crack, floor
    intact. Any JSON a model writes on Windows may carry a BOM - read model
    output with `encoding="utf-8-sig"` everywhere. The near-miss is the point:
    an unverified referee manufactures false discriminators as readily as a
    model manufactures false-greens. Verify the verifier.

16. **Breadth has a waterline that depth and difficulty do not - and
    decomposition is the fix (quality, not just cost).** The program's floor
    held against knots, interactions, spec gaps, multi-file work, adversarial
    certification, and 20-stage compounding chains. It cracked on BREADTH: one
    spec with N independent requirements. Monolithic Spark at N=160 (11 runs,
    fresh spec each): 5 clean, 5 dropped 2-5 low-salience one-liner rules
    (suffix_trim, upper, strip, abs_cap, bool_flip - the boring ones, ~1%
    per-rule silent omission, still passing visible checks), 1 produced
    non-importable code. ~55% of runs imperfect. Cross-model: Luna dropped 3/160
    too - the waterline is general, not Spark-specific. Adjudicated real, not a
    harness artifact (isolating probes showed rules literally unimplemented).
    THE FIX: split the 160 rules into 4 scoped passes of 40 (model preserves
    prior passes, focuses on its 40). Decomposed N=160x4: 5/5 runs perfect,
    zero drops, zero breaks. Scoping context per pass drove a ~55%-imperfect
    rate to 0%. This is the crate/DAG thesis (CART0) proven with a QUALITY
    delta - not just the ~35% context-cost delta the live pilot showed. Cost:
    4x the calls. Operating rule: past ~50-80 independent requirements in one
    prompt, cheap models silently drop some; decompose into <=40-requirement
    scoped passes and the drops vanish. The referee (per-requirement isolating
    probes) is what makes the drop visible at all - aggregate pass/fail hides it.

17. **Small samples manufacture findings; K<=5 is a rumor, not a result.
    (This retracts parts of lessons 16.)** The overnight breadth hunt produced
    three exciting claims that ALL dissolved under K=10: (a) "monolithic recall
    degrades ~55% at N=160" - a single high-variance batch that happened to
    cluster failures; matched K=10 on the SAME seeds got 8/10 clean. (b) "the
    drop is a Codex-CLI edit-loop artifact, RESOLVED" - edit and emit modes
    have the IDENTICAL 80% clean rate at N=160 (K=10 each); the edit-loop does
    not cause the drops. (c) "decomposition into 4x40 passes rescues it (5/5
    clean)" - P(5/5 clean | 0.8 base rate) = 0.33, not significant; it was luck.
    What actually survives K=10: cheap-model single-shot recall on 160-1000
    independent requirements is ~80-100% per run with RARE stochastic
    imperfections (~1 rule), NOT a capability wall (emit holds to 1000 rules).
    The one durable real distinction is FAILURE MODE by interface: file-edit
    fails by silently dropping ~1 rule (insidious - can pass aggregate checks);
    text-emit fails by producing unparseable output (loud - the referee always
    catches it). For a verified pipeline, prefer the interface that fails loud.
    Method rule: report clean-rate with n; never ship an effect measured at
    K<=5; if a rescue looks perfect, compute P(that many clean | base rate)
    before believing it. The program's own discipline (lessons 14/15) applied
    to its own headline results - and most did not survive.

18. **The moat is session custody, not intelligence - and the counter-
    architecture is the anchor crate.** Final receipt of the 2026-07-18 program:
    the session that proved capability is commoditized at every tier of both
    vendors billed ~$760 API-equivalent - and 92% of it was the ORCHESTRATOR'S
    OWN main loop (1,171 turns x ~250k-token conversation = 618M cache-read
    tokens at frontier prices). The workers who did all the measurable labor
    cost $61; the entire cross-vendor GPT program cost ~$10. The frontier moat
    is therefore not thinking - it is the architecture that keeps your working
    state resident in their context window, charging rent on every re-read.
    Every measurement this program produced converges on the same escape,
    which is CART0/anchor-crate (the side project the original benchmarks
    spawned): state lives in YOUR files, pointer-addressed and bounded
    (measured -35% context at zero quality cost); drivers are SHORT-LIVED and
    NARROW-CONTEXT, spawned per phase from a handoff crate and discarded;
    workers are cheap and stateless; referees are deterministic and free.
    Corollary that must be said out loud: the orchestrator is not exempt.
    Lesson 7 (efficiency is context) applies MOST to the driver's own loop -
    a marathon frontier session is the single most expensive object in the
    entire architecture, and the one every other lesson quietly assumed was
    free. Run the driver like a crate visitor, not a tenant.

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
