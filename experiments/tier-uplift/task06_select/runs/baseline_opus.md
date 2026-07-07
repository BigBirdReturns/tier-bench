# Review of select.py

## Task
`select(items, k)` must choose exactly `k` distinct items to maximize total value
subject to: total weight of chosen items divisible by 3. Return the max value, or
`None` if impossible / `k` out of range.

## Verdict: WRONG

The implementation is incorrect. It uses a greedy "top-k by value, then repair with
at most ONE swap" strategy that cannot reach optima requiring two or more swaps.

## Why the strategy is flawed

The algorithm:
1. Takes the top-k items by value (`chosen`).
2. If their weight sum is already divisible by 3, returns it (fine — that is optimal).
3. Otherwise it tries every single swap (remove one `chosen` item, add one `rest`
   item) and keeps the best swap that lands the weight sum on a multiple of 3.

The fatal gap is step 3: it only ever considers replacing **one** chosen item. The
true optimum may require replacing **two (or more)** chosen items simultaneously.

Residue argument (mod 3): let the top-k weight sum have residue `r != 0`. A single
swap of chosen item `c` for rest item `d` shifts the residue by `(w_d - w_c) mod 3`.
It is easy to arrange weights so that:
- No single swap produces the needed shift `-r (mod 3)`, yet
- A pair of swaps composes two individually "insufficient" shifts into the needed one.

Concretely: make every chosen item have weight residue 0 except one with residue 1
(so the top-k residue is 1), and make every non-chosen candidate have residue 1.
Then the only single-swap shifts available are 0 (swap the residue-1 chosen for a
residue-1 rest) or +1 (swap a residue-0 chosen for a residue-1 rest). Neither turns
residue 1 into 0. But two `+1` swaps compose to `+2`, taking residue 1 to 0. The
code never explores that two-swap move, so it returns `None` (or a suboptimal value)
even though a valid selection exists.

## Concrete counterexample

```
items = [(10,1), (9,3), (8,3), (5,1), (4,1)]
k = 3
```

Weights mod 3: item0 -> 1, item1 -> 0, item2 -> 0, item3 -> 1, item4 -> 1.

Execution of the implementation:
- `order` (by descending value) = [0, 1, 2, 3, 4]; `chosen` = [0, 1, 2].
- `wsum(chosen)` = 1 + 3 + 3 = 7, `7 % 3 = 1` != 0, so it enters the repair loop.
- `rest` = [3, 4]. Every single swap yields weight sum 5 or 7:
  - replace 0 with 3/4: 3+3+1 = 7 (residue 1)
  - replace 1 with 3/4: 1+3+1 = 5 (residue 2)
  - replace 2 with 3/4: 1+3+1 = 5 (residue 2)
  None is divisible by 3, so `best` stays `None`.
- **Returns `None`.**

Correct answer (brute force over all C(5,3)=10 triples): the only triple whose
weight is divisible by 3 is items {0,3,4} with weights 1+1+1 = 3 and value
10+5+4 = **19**. (All other triples have weight residue 1 or 2.)

- Implementation returns: `None`
- Correct answer: `19`

Verified programmatically against an exhaustive brute-force solver: impl -> None,
correct -> 19.

The single-swap repair skips the valid optimum {0,3,4}, which is a **double** swap
away from the top-3 (drop items 1 and 2, add items 3 and 4).

COUNTEREXAMPLE: items=[(10,1),(9,3),(8,3),(5,1),(4,1)]; k=3
