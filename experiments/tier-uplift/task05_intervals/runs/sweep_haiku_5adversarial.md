# Adversarial Semantics Review: intervals.py

## Summary
Four distinct algorithmic bugs found. Three are critical logic errors that fail on specific inputs; one is a precision issue.

---

## Bug 1: `merge_intervals()` — Off-by-one comparison breaks touching intervals

**Location:** Line 16  
**Function:** `merge_intervals()`

**The Issue:**
The code checks `if cur[0] < last[1]` to detect overlap, but the docstring explicitly states "Touching intervals (e.g. [1,2] and [2,3]) are considered to overlap and should merge." When two intervals touch (last endpoint equals next start), the condition `cur[0] < last[1]` evaluates to False, preventing the merge.

**Why it's wrong:**
- Intervals [1,2] and [2,3] touch at point 2
- For [1,2]: last[1] = 2
- For [2,3]: cur[0] = 2
- Check: `2 < 2` → False → no merge
- But the spec requires they merge to [1,3]

**Breaking input:**
```python
merge_intervals([(1, 2), (2, 3)])
# Returns: [(1, 2), (2, 3)]
# Expected: [(1, 3)]
```

**Fix:** Change line 16 to `if cur[0] <= last[1]:`

---

## Bug 2: `contains_point()` — Strict inequality excludes endpoints

**Location:** Line 31  
**Function:** `contains_point()`

**The Issue:**
The docstring states "(endpoints included)" but line 31 checks `if s < p < e`, using strict inequality. This excludes both endpoints, contradicting the specification.

**Why it's wrong:**
- Point p=1 in interval [1,2] should be contained (endpoints included)
- Check: `1 < 1 < 2` → False
- Point p=2 in interval [1,2] should be contained
- Check: `1 < 2 < 2` → False
- Neither endpoint is considered contained

**Breaking input:**
```python
contains_point([(1, 2), (3, 5)], 1)
# Returns: False
# Expected: True (1 is the left endpoint)

contains_point([(1, 2), (3, 5)], 2)
# Returns: False
# Expected: True (2 is the right endpoint)
```

**Fix:** Change line 31 to `if s <= p <= e:`

---

## Bug 3: `max_non_overlapping()` — Wrong sort key defeats greedy algorithm

**Location:** Line 41  
**Function:** `max_non_overlapping()`

**The Issue:**
Classic interval scheduling (selecting maximum mutually non-overlapping intervals) requires a greedy strategy of always choosing the interval that **ends earliest**. The code sorts by start position instead, which produces suboptimal results. Sorting by start is a fundamentally different algorithm that doesn't solve the interval scheduling problem.

**Why it's wrong:**
- Greedy strategy: pick interval with earliest end, move forward in time
- Current code: pick interval with earliest start, then check if next interval fits
- When an early-starting interval spans a large range, it blocks many non-overlapping intervals that could fit in the same space

**Breaking input:**
```python
max_non_overlapping([(1, 100), (2, 3), (4, 5)])
# Current execution:
#   Sort by start: [(1, 100), (2, 3), (4, 5)]
#   Pick [1, 100], end=100, count=1
#   Check [2, 3]: 2 >= 100? No, skip
#   Check [4, 5]: 4 >= 100? No, skip
#   Return: 1
#
# Optimal solution: pick [2, 3] and [4, 5]
# Expected: 2
```

**Fix:** Change line 41 to sort by end position: `s = sorted(intervals, key=lambda x: x[1])`  
Also change the logic: initialize `end = s[0][1]`, and for each candidate, check `if cur[0] > end:` (strictly greater, since touching is overlapping per the spec).

---

## Bug 4: `busiest_point()` — Incomplete point coverage in sweep algorithm

**Location:** Lines 54-58  
**Function:** `busiest_point()`

**The Issue:**
The algorithm only checks the **start point** of each interval (line 55: `count = sum(1 for a, b in intervals if a <= s <= b)`). For a complete and correct sweep-line algorithm finding the busiest point, the algorithm should also consider **end points** (and arguably points just before them, or run a proper event-based sweep). This can miss the actual maximum or be inefficient.

**Why the approach is incomplete:**
The busiest point (maximum overlap) can occur anywhere, but critical transitions happen at interval boundaries. By checking only starts, the algorithm:
1. May miss the true busiest point if it occurs between events
2. Is inefficient (O(n²)) compared to a proper sweep-line with event points (O(n log n))

**Problematic input:**
```python
busiest_point([(1, 10), (11, 20)])
# Checks points 1 and 11
# Point 1: covered by [1, 10] only, count=1
# Point 11: covered by [11, 20] only, count=1
# Returns 1 (or 11)
# This works, but the algorithm is fragile.

# Better test case showing the issue:
busiest_point([(1, 5), (6, 10), (2, 7)])
# Checks points 1, 6, 2
# Point 1: in [1, 5], count=1
# Point 6: in [6, 10] and [2, 7], count=2 ← Best
# Point 2: in [1, 5] and [2, 7], count=2
# Returns 6, but the real busiest region is [6,7] with count=2
# The algorithm happens to find *a* busiest point, but logic is incomplete
```

**The real issue:** If intervals were `[(5, 10), (1, 4), (6, 20)]`, sorting by start gives checks at points 1, 5, 6. But the absolute busiest might be at point 7-10 covered by [5,10] and [6,20], which isn't a start point checked. The algorithm risks returning a suboptimal answer or None if no interval start is covered by multiple intervals.

---

## Summary of Fixes

| Function | Line | Change | Severity |
|----------|------|--------|----------|
| `merge_intervals` | 16 | `<` → `<=` | Critical |
| `contains_point` | 31 | `s < p < e` → `s <= p <= e` | Critical |
| `max_non_overlapping` | 41 | Sort by `x[1]` (end), not `x[0]` (start) | Critical |
| `busiest_point` | 54–58 | Consider end points in sweep; ideally refactor to event-based sweep | Medium |
