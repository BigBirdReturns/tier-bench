# Authoring brief — 3 new novel-reasoning hidden-graded tasks

**Who this is for:** the driver (Fable, effort HIGH) authoring task content. This
document is the bar; `acceptance.py` is the mechanical check against that bar.
Sonnet prep built the scaffold so Fable spends its tokens on the one thing that
can't be plumbed: the subtle reasoning content itself.

## Why these tasks exist

`LESSONS.md` rule 4, measured, not asserted: a competent cheap model implements to
*any* spec you hand it — even hidden-graded, even with a semantic judge (6/6
measured on the existing corpus). The frontier residue is not richer specs; it is
**novel reasoning where the answer must be derived, not looked up** — the
`task06_select` shape (`experiments/tier-uplift/task06_select/`): a plausible,
carefully-written implementation that is subtly wrong on ~2% of inputs, findable
only by reasoning about the objective and constructing a counterexample, not by
pattern-matching a bug.

The existing corner is fully settled (`run/KNOWN_CORNER.md`) — 5/5 valid tasks
cleared, at most one rung of escalation. That is not evidence the frontier gap is
closed; it is evidence the *ruler* needs to grow in the judgment-derivation
direction, not the spec-following direction. These 3 slots are that growth.

## The bar — every new task MUST clear all five acceptance criteria

1. **(a) The grader is deterministic.** Same candidate, run twice → identical
   verdict (exit code) both times. No wall-clock, no randomness, no network.
2. **(b) The naive/unsolved candidate FAILS the hidden grader.** The obvious,
   plausible-looking implementation — the one a competent-but-not-searching
   solver would write first — must be provably wrong, not just inelegant.
3. **(c) A reference solution PASSES.** At least one correct implementation
   exists and is committed (privately, alongside the hidden grader) so the bar
   is provably clearable, not a moving target.
4. **(d) `breadth_tasks.py` would list it valid.** The hidden grader's filename
   must be one of the recognized hidden-grader names
   (`hidden_tests.py`, `hidden_oracle.py`, `grader.py` — see
   `experiments/breadth/breadth_tasks.py:HIDDEN_GRADER_NAMES`), so that once the
   finished task is promoted into `experiments/tier-uplift/` (or given a
   `tasks/*.json` manifest with `hidden_files` + `hidden_run_command`), the
   breadth map picks it up automatically — no harness changes required.
5. **(e) The solver never sees the hidden grader.** `spec.md` (and any other
   solver-facing file) must not name, quote, or embed the hidden grader's
   filename or its logic. If a solver can read the answer key, the task
   measures nothing (this is the exact failure `breadth_tasks.py`'s docstring
   calls "answer-key theatre").

## Density requirement

"Dense" means: no scaffolding busywork, no multi-step spec that rewards
following instructions carefully. One tight function/class, one underspecified
or easily-mis-generalized edge in its *objective*, findable only by reasoning
about that objective — not by reading more of the spec. If the task can be
solved by an agentic loop that just iterates against visible tests, it is not
novel-reasoning-shaped; redesign it.

## The grader contract (so acceptance.py can stay task-agnostic)

Every hidden grader in a slot is a standalone script invoked as:

```
python <slot>/<hidden_grader_filename> <path-to-candidate-module>
```

- Exit code `0` → the candidate PASSES (it does NOT contain/trigger the flaw, or
  — for counterexample-style tasks like task06 — the candidate module itself
  proves the flaw, e.g. by defining a function `counterexample()` the grader
  calls and checks).
- Exit code non-zero → FAILS.
- The grader may print whatever diagnostic it wants to stdout/stderr; only the
  exit code is load-bearing for pass/fail. Determinism is judged on exit code
  (and, best-effort, stdout) across repeat runs with the same input.
- The grader must not read `spec.md` or any other solver-facing file to decide
  the verdict — it grades the candidate module only.

This mirrors the existing `hidden_tests.py` / `hidden_oracle.py` / `grader.py`
convention in `experiments/tier-uplift/` closely enough that promotion is a
file move, not a rewrite.

## Filling a slot

Each `t_novel_0N/` currently holds three placeholders:

```
spec.md              — solver-facing spec. TODO: replace with the real, tight spec.
NAIVE.py             — TODO: the naive/plausible candidate that FAILS the grader.
REFERENCE.py         — TODO: a correct candidate that PASSES the grader.
<hidden_grader>.py   — TODO: the hidden grader itself (name already fixed per slot,
                        see below — one of each recognized name for variety).
```

| Slot | Hidden grader filename | Shape to aim for |
|---|---|---|
| `t_novel_01` | `grader.py` | counterexample-construction (task06-shape) |
| `t_novel_02` | `hidden_oracle.py` | boundary/edge-classification the naive impl gets wrong on a rare input class |
| `t_novel_03` | `hidden_tests.py` | derivation task where the naive impl over-generalizes a pattern that breaks once |

Do not rename the hidden-grader files — their names are already the criterion
(d) anchor. Do not touch `acceptance.py` (that would be a GATED change to a
grader per `adapt.py` — propose it, don't self-apply it).

## Verifying a filled slot

```
python experiments/breadth/authoring/acceptance.py --slot experiments/breadth/authoring/t_novel_01 \
  --candidate NAIVE.py --reference REFERENCE.py
```

Prints PASS/FAIL for each of (a)-(e). All five must be PASS before the task is
committed as finished content (still authoring-only — no solve-loop, no Fable
spent grading its own output; `acceptance.py` is deterministic Python, not a
model call).
