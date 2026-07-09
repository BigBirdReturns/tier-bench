# t_novel_03 — deferred ordering

Order jobs under precedence constraints so the cheapest jobs land at the END of
the schedule.

## What you must submit

A Python module defining, at top level:

```python
def order(n: int, edges: list) -> list | None:
    """Jobs are 1..n. Each edge (a, b) means job a must run before job b.
    Return the schedule (a list containing each job exactly once, every
    constraint respected) selected by the objective below, or None if no
    valid schedule exists (the constraints contain a cycle)."""
```

## The objective

Among all valid schedules, return the one where:

1. the **last** job's number is as small as possible;
2. subject to that, the **second-to-last** job's number is as small as possible;
3. and so on, position by position, from the end toward the front.

This objective selects exactly one schedule — return it.

## Worked example

`n = 3`, `edges = [(3, 1)]` (job 3 must run before job 1). The valid schedules
are `[3, 1, 2]`, `[3, 2, 1]`, and `[2, 3, 1]`. Their last jobs are 2, 1, 1 —
so the last job must be 1, eliminating `[3, 1, 2]`. Of the rest, the
second-to-last jobs are 2 and 3 — so the answer is `[3, 2, 1]`.

## Input guarantees

- `1 <= n <= 200`; each edge is a pair of ints in `1..n`.
- `edges` may contain duplicates. An edge `(a, a)` is a cycle (no valid
  schedule exists).
- Brute-forcing all schedules is not viable at these sizes; your function must
  compute the answer directly.

## Further examples

- `order(3, [(1, 2), (2, 3)])` → `[1, 2, 3]` (fully constrained chain)
- `order(3, [(1, 2), (2, 3), (3, 1)])` → `None` (cycle)

Your module will be evaluated on inputs beyond these examples.
