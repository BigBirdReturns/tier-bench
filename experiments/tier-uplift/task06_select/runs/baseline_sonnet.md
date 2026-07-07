# Review of select.py

## Verdict: INCORRECT

`select()` does not compute the true maximum-value, exactly-k, weight-sum-divisible-by-3
selection on all inputs. It is a greedy-plus-single-swap heuristic, and both parts of that
heuristic are unsound:

1. **Greedy seed**: it starts from the unconstrained top-k-by-value set (`chosen`).
2. **Repair step**: if that set's weight sum isn't ≡ 0 (mod 3), it tries every
   *single* remove-one-add-one swap between `chosen` and the remaining items (`rest`),
   and returns the best value among swaps that happen to fix the residue — or `None`
   if no *single* swap fixes it.

The fatal flaw is in step 2: the algorithm conflates "no 1-for-1 swap from the naive
top-k set achieves the quota" with "no valid k-subset achieves the quota at all." These
are not the same thing. A valid, even optimal, selection may require replacing **two or
more** items simultaneously (a "swap distance" of 2+), or may simply not overlap with the
top-k set the way a single swap assumes. Because the search space explored is only
`chosen` itself, plus subsets at swap-distance exactly 1 from `chosen`, any optimal
solution at swap-distance ≥ 2 from the naive top-k is invisible to this code — it will
wrongly report `None` (or, in other inputs, would wrongly report a suboptimal value if a
worse-than-optimal single swap happens to satisfy the residue while the true optimum
needed a double swap and stayed unseen).

## Concrete counterexample

```
items = [(100,1), (90,1), (80,1), (70,1), (10,2), (10,2)]
k = 4
```

- Indices 0–3 have weight 1 each (residue 1 mod 3), values 100/90/80/70.
- Indices 4–5 have weight 2 each (residue 2 mod 3), values 10/10.

**What the algorithm returns:** `None`.

Trace: `chosen = [0,1,2,3]` (top-4 by value), `wsum = 1+1+1+1 = 4`, `4 % 3 = 1 ≠ 0`, so it
enters repair. `rest = [4,5]`. Every candidate swap removes one weight-1 item from
`chosen` and adds one weight-2 item from `rest`, giving a candidate with 3 weight-1 items
+ 1 weight-2 item: weight = 3 + 2 = 5, and `5 % 3 = 2 ≠ 0` for *all 8* such candidates
(4 choices of `c` × 2 choices of `r`). So `best` never gets set, and the function returns
`None`.

**What the correct answer is:** `210`, achieved by `{100, 90, 10, 10}` — i.e. selecting
indices `{0, 1, 4, 5}`: weight = 1+1+2+2 = 6, which is divisible by 3.

Proof this is the true optimum (exhaustive case analysis over the only two possible
"shapes" for a size-4 subset here, since only weights 1 and 2 exist and only two weight-2
items exist): a size-4 subset must use `x` items of weight 1 and `4-x` items of weight 2,
with `4-x ≤ 2` (only two weight-2 items exist), so `x ∈ {2,3,4}`.
- `x=4`: weight = 4, `4%3=1` — invalid.
- `x=3`: weight = 3+2=5, `5%3=2` — invalid.
- `x=2`: weight = 2+4=6, `6%3=0` — **valid**, and this is the only valid shape.

Within the `x=2` shape, both weight-2 items must be used (there are only two), and value
is maximized by picking the two highest-value weight-1 items (100 and 90), giving
`100+90+10+10 = 210`. Brute-force search over all `C(6,4)=15` subsets confirms `210` is
the global optimum (selection `(0,1,4,5)`), independently verified with a Python script
in this review.

So on this input the function returns `None` ("no valid selection exists") when a valid
selection worth 210 in fact exists — an unambiguous, maximal-severity bug: it's not just
suboptimal, it's a false negative on feasibility itself.

## Root cause / general lesson

The repair heuristic implicitly assumes the optimal (or any) quota-satisfying subset is
always within Hamming/swap-distance 1 of the unconstrained top-k set. That assumption is
false in general: whenever fixing the residue requires swapping two or more items at
once (as happens whenever the "wrong" residue items in `chosen` and the "right" residue
items in `rest` don't pair up 1-for-1 to hit residue 0), the true optimum — or any valid
solution — can be completely missed, and the function incorrectly reports infeasibility
(`None`) or, in other constructions, could return a valid but non-optimal value while a
higher-value 2-swap solution goes unexamined.

COUNTEREXAMPLE: items=[(100,1),(90,1),(80,1),(70,1),(10,2),(10,2)]; k=4
