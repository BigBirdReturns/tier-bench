# Correctness Review: intervals.py

## Bugs Found

1. **Line 16, `merge_intervals()`: Incorrect boundary condition for touching intervals**
   - Bug: Uses `if cur[0] < last[1]` to detect overlap, but this excludes touching intervals where `cur[0] == last[1]`.
   - The spec explicitly states: "Touching intervals (e.g. [1,2] and [2,3]) are considered to overlap and should merge."
   - Should be: `if cur[0] <= last[1]`
   - Concrete input that exposes it: `[[1,2], [2,3]]` returns `[[1,2], [2,3]]` but should return `[[1,3]]`

2. **Line 31, `contains_point()`: Excludes endpoints despite docstring**
   - Bug: Uses `if s < p < e` which excludes both endpoints, contradicting the docstring "endpoints included".
   - Should be: `if s <= p <= e`
   - Concrete input that exposes it: `contains_point([[1,2]], 1)` returns `False` but should return `True`

3. **Line 45, `max_non_overlapping()`: Incorrect boundary condition for touching intervals**
   - Bug: Uses `if cur[0] >= end` to determine if intervals don't overlap. When `cur[0] == end`, intervals are touching, which per spec should count as overlapping and not both be selected.
   - Should be: `if cur[0] > end`
   - Concrete input that exposes it: `[[1,2], [2,3], [4,5]]` returns `3` (picks all three) but should return `2` (cannot pick [1,2] and [2,3] together since they're touching)

4. **Line 41, `max_non_overlapping()`: Wrong sorting criterion for greedy algorithm**
   - Bug: Sorts by start time instead of end time. The classic interval scheduling maximization problem requires sorting by END time to ensure the greedy algorithm selects the maximum number of non-overlapping intervals.
   - Should be: `s = sorted(intervals, key=lambda x: x[1])` (sort by end time, not start time)
   - Concrete input that exposes it: `[[1,10], [2,3], [4,5]]` returns `1` but should return `2` (with correct sort: pick [2,3] and [4,5])
