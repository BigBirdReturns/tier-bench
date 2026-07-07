# Correctness review: intervals.py

1. **Line 16, `merge_intervals`** — Touching intervals are not merged because the overlap test uses `<` instead of `<=`; the module docstring explicitly requires touching intervals (e.g. `[1,2]` and `[2,3]`) to merge. Input `merge_intervals([[1,2],[2,3]])` returns `[[1,2],[2,3]]` instead of the required `[[1,3]]`.

2. **Line 17, `merge_intervals`** — Mutates the caller's interval objects (unintended side effect) despite the docstring promising a "new" list; `merged` holds references to the original interval lists and `last[1] = ...` writes through them. Input `a=[1,3]; b=[2,7]; merge_intervals([a,b])` leaves `a == [1,7]` (the caller's `a` is corrupted). Additionally this raises `TypeError` if intervals are passed as tuples, since item assignment on a tuple fails: `merge_intervals([(1,3),(2,7)])`.

3. **Line 31, `contains_point`** — Uses strict inequalities `s < p < e`, so endpoints are excluded even though the docstring says "endpoints included." Input `contains_point([(1,5)], 1)` returns `False` but should return `True` (same for `p == 5`).

4. **Lines 41 & 43, `max_non_overlapping`** — Wrong greedy algorithm: interval scheduling maximization must sort by END time, but this sorts by START (`key=lambda x: x[0]`) and seeds `end` from the earliest-starting interval, which can be a large blocking interval. Input `max_non_overlapping([[1,10],[2,3],[4,5]])` returns `1` (keeps `[1,10]`) but the correct answer is `2` (choose `[2,3]` and `[4,5]`).

5. **Line 45, `max_non_overlapping`** — Even with a correct sort, the acceptance test `cur[0] >= end` treats touching intervals as non-overlapping, contradicting the docstring's "touching counts as overlapping"; it should be `cur[0] > end`. Input `max_non_overlapping([[1,2],[2,3]])` returns `2` but, since touching counts as overlapping, the correct answer is `1`.
