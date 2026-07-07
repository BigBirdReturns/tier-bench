# Answer key — task 06 (PRIVATE)

**Novel-reasoning probe.** No line is "wrong"; the whole approach is subtly
incomplete. There is nothing to pattern-match — a solver only succeeds by
reasoning about the objective and constructing a counterexample.

**The flaw:** the implementation assumes the optimum is either the top-k by value,
or one single swap away from it. But the best *quota-valid* selection can require
changing **two or more** items relative to the top-k — or not contain the top-k at
all. So `select` can return a suboptimal value, or even `None` when a valid
selection exists (whenever the fix needs ≥2 swaps).

Verified counterexample: `items=[(1,1),(1,1),(1,0),(1,0)], k=2` → subject returns
`None`, correct answer is `2` (choose the two weight-0 items: weight 0 % 3 == 0).

The flaw differs from the reference on ~2.25% of small inputs — subtle enough that
random poking rarely hits it; you find it by understanding *why* single-swap
repair is insufficient.

**Grading (objective):** extract the solver's claimed `(items, k)` and run
`grader.py --check`. Credit iff `subject(items,k) != reference(items,k)` on a valid
input. Merely saying "greedy looks risky" without a working counterexample does
NOT count — the bar is a provable break.
