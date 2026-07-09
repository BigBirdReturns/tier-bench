# Sonnet prep — paste-prompt (ends in the READY/go handoff, or the blocker)

Paste the block below into a fresh **Sonnet** session on latest `main`. It does the
keyless groundwork and prints the Fable handoff line **only if every rail is green**
— otherwise it prints the blocker and stops. (Check (c) uses the tiered shard check:
gold `axm-verify` where the AXM toolchain exists, the committed sha256 sidecar where
it doesn't — the result names which level it verified at.)

---

```
You are the Sonnet prep driver for the breadth program in this repo (tier-bench, latest
main). Do PREP ONLY: do not switch models, do not author the hard task content yourself,
do not run Fable, do not run the solve-loop. Everything below is keyless / $0.

STEP 1 — ORIENT. Read: CLAUDE.md (START HERE block), experiments/breadth/LESSONS.md,
HANDOFF.md §9, experiments/breadth/run/KNOWN_CORNER.md.

STEP 2 — RAILS GREEN-CHECK (report PASS/FAIL for each, keyless):
  a. python experiments/breadth/smoke.py                          # grade->ledger->map spine
  b. python experiments/breadth/breadth_tasks.py                  # the valid hidden-grader set
  c. python -m capability_harness.lens_shard memory/lenses/shard  # tiered integrity: GOLD
     #  (axm-verify) where the toolchain exists, SIDECAR (committed sha256, anchored to a
     #  gold PASS at seal time) where it doesn't. PASS at either level is green; the level
     #  and any unmeasured gap are named in the output. FAIL at either level blocks READY.
  d. 3-line check: adapt.record(..., target="grader", applied=True) comes back applied=False
  e. 3-line check: ledger.reconcile flags an unaccounted bill

STEP 3 — CONFIRM THE RESIDUAL. From KNOWN_CORNER: state explicitly whether any valid task
is unsettled. If the residual is EMPTY, say so and note that the only productive Fable work
is AUTHORING new novel-reasoning tasks — not a solve run.

STEP 4 — CHEAP HOUSEKEEPING. If ROADMAP.md's STATE table is stale vs git history, fix it
(doc-only commit).

STEP 5 — SCAFFOLD THE AUTHORING RUN so Fable only has to think, not plumb. Create
experiments/breadth/authoring/ containing:
  - AUTHORING_BRIEF.md: the bar for each new task — DENSE and NOVEL-REASONING (counterexample
    construction / derivation where a full spec does NOT hand over the answer, task06-shape),
    hidden-graded, must clear acceptance: (a) grader deterministic; (b) the unsolved/naive
    candidate FAILS the hidden grader; (c) a reference solution PASSES; (d) breadth_tasks.py
    lists it valid; (e) the solver prompt never contains the hidden grader. Target: 3 tasks.
  - 3 empty slots t_novel_01..03 (spec.md placeholder + the expected hidden-grader filename).
  - acceptance.py: given a slot + candidate + reference, runs (a)-(d) and prints PASS/FAIL
    per criterion. You write the harness; Fable fills the subtle content.
Commit the scaffold to this branch.

STEP 6 — FINAL. If and ONLY IF every STEP 2 check is PASS and the scaffold + acceptance.py
are committed, print EXACTLY this and nothing after:

  READY — rails green, residual empty, authoring scaffold in place.
  Switch this session to Fable at effort HIGH, then type: go
  (On `go` I will author 3 dense novel-reasoning hidden-graded tasks into
   experiments/breadth/authoring/, verify each with acceptance.py — unsolved FAILS,
   reference PASSES, breadth_tasks lists it — then commit. No solve-loop, no wasted Fable.)

If any check FAILS, do NOT print the READY line. Print the blocker and stop.
```
