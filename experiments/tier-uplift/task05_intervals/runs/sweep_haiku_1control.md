# Control Flow & Boundaries Review: intervals.py

## Issues Found

### 1. merge_intervals, line 16 — Off-by-one in merge condition
**Location:** Line 16  
**Function:** `merge_intervals`  
**Issue:** Condition `if cur[0] < last[1]:` uses strict inequality, failing to merge touching intervals per spec.  
**Concrete example:** intervals = [[1, 2], [2, 3]] → returns [[1, 2], [2, 3]] instead of [[1, 3]]  
**Fix:** Change to `if cur[0] <= last[1]:`

### 2. contains_point, line 31 — Boundary exclusion contradicts docstring
**Location:** Line 31  
**Function:** `contains_point`  
**Issue:** Condition `if s < p < e:` excludes endpoints, but docstring states "(endpoints included)".  
**Concrete example:** contains_point([[1, 3]], 1) → returns False instead of True  
**Fix:** Change to `if s <= p <= e:`

### 3. max_non_overlapping, line 45 — Off-by-one in scheduling condition
**Location:** Line 45  
**Function:** `max_non_overlapping`  
**Issue:** Condition `if cur[0] >= end:` selects overlapping touching intervals, contradicting docstring "(touching counts as overlapping)".  
**Concrete example:** max_non_overlapping([[1, 2], [2, 3]]) → returns 2 instead of 1  
**Fix:** Change to `if cur[0] > end:`

## Summary
Three boundary condition errors: two strict-inequality issues preventing correct merging and point containment per spec, one off-by-one in interval scheduling logic.
