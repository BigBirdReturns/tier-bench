# t_novel_01 — break `pick`

`subject.py` in this directory implements:

```python
def pick(xs, k):
    """Return the maximum total value of exactly k picks from xs such that no two
    picked positions are adjacent (|i - j| > 1 for every pair of picked indices
    i, j). Return None if no such selection of exactly k positions exists."""
```

The strategy: greedily take positions in decreasing value order (ties broken by
lower index), skipping positions adjacent to one already taken. If that reaches
exactly `k` picks, return their total. Otherwise run a repair pass: try
exchanging one chosen position for one unchosen position and greedily extending,
keeping the best selection that reaches exactly `k`. If nothing reaches `k`,
return None. Read the code — it is short and it is the ground truth for what the
function does.

**The claim:** `pick` is correct — for every valid input it returns the true
maximum total (or None exactly when no valid selection exists).

**The claim is false.** Your job is to prove it with a concrete input.

## What you must submit

A Python module defining, at top level:

```python
def counterexample():
    """Return (xs, k) on which pick(xs, k) differs from the correct answer."""
```

Constraints on the returned input — it must satisfy all of these to be judged:

- `xs` is a list of ints, `1 <= len(xs) <= 12`, each value `0 <= v <= 50`
- `k` is an int, `0 <= k <= len(xs)`

Any provable break counts: a wrong maximum, or a None where a valid selection
exists, or a value where the correct answer is None. Merely arguing the strategy
"looks risky" counts for nothing — the bar is an input on which the output is
provably wrong. Your module may compute the answer however you like (or just
return a hard-coded input); only the returned `(xs, k)` is judged.

## Examples of `pick` behaving correctly (these are NOT counterexamples)

- `pick([1, 2], 1) == 2` — take the 2.
- `pick([3, 1, 3], 2) == 6` — positions 0 and 2 are non-adjacent.
- `pick([1, 2, 3], 3) is None` — three picks from three positions must include
  an adjacent pair.
