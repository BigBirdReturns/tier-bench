# CONTRACTS & ERRORS Review: intervals.py

## Issues Found

### 1. merge_intervals, line 16: Touching intervals not merged
**Function:** `merge_intervals`  
**Line:** 16  
**Issue:** Uses `if cur[0] < last[1]:` to detect overlap, but this excludes touching intervals. Docstring requires [1,2] and [2,3] to merge.  
**Concrete input:** `[[1, 2], [2, 3]]` returns `[[1, 2], [2, 3]]` (unchanged) instead of `[[1, 3]]`  
**Fix:** Change to `if cur[0] <= last[1]:`

### 2. merge_intervals, line 17: Mutates input intervals in place
**Function:** `merge_intervals`  
**Line:** 17  
**Issue:** `last[1] = max(last[1], cur[1])` modifies the original interval object. Caller expects new list without side effects.  
**Concrete input:** `intervals = [[1, 5], [2, 3]]; merge_intervals(intervals); intervals[0][1]` is now 5 (was modified)  
**Fix:** Create new interval tuples instead of mutating: `merged.append((last[0], max(last[1], cur[1])))`

### 3. contains_point, line 31: Excludes endpoints despite docstring
**Function:** `contains_point`  
**Line:** 31  
**Issue:** Uses `if s < p < e:` which excludes endpoints, contradicting docstring "endpoints included".  
**Concrete input:** `contains_point([[1, 3]], 1)` returns `False` instead of `True`; `contains_point([[1, 3]], 3)` returns `False` instead of `True`  
**Fix:** Change to `if s <= p <= e:`

### 4. merge_intervals, line 12: No validation of interval structure
**Function:** `merge_intervals`  
**Line:** 12  
**Issue:** Assumes each element is indexable with [0] and [1]; no check for malformed intervals.  
**Concrete input:** `merge_intervals([None])` crashes with TypeError; `merge_intervals(["abc"])` crashes with TypeError  
**Mitigation:** Add validation: check each interval is a sequence of length ≥ 2

### 5. total_covered, line 25: Silent garbage on malformed intervals
**Function:** `total_covered`  
**Line:** 25  
**Issue:** Assumes merge_intervals output contains valid [start, end]; no validation that start ≤ end. Returns incorrect sum for inverted intervals.  
**Concrete input:** `total_covered([[5, 1]])` computes `1 - 5 = -4`, sum is -4 (nonsensical)  
**Mitigation:** Validate start ≤ end before calculation

### 6. busiest_point, line 59: Returns None silently on empty input
**Function:** `busiest_point`  
**Line:** 59  
**Issue:** Returns `None` if intervals is empty. Return type is not documented as Optional; caller may assume a valid point is returned.  
**Concrete input:** `busiest_point([])` returns `None` without raising  
**Mitigation:** Raise `ValueError` on empty input or document Optional return type

### 7. max_non_overlapping, line 41: No validation of interval structure
**Function:** `max_non_overlapping`  
**Line:** 41  
**Issue:** Assumes intervals contain indexable [0] and [1]; no structure validation.  
**Concrete input:** `max_non_overlapping(["x"])` crashes with TypeError  
**Mitigation:** Add validation check

### 8. busiest_point, line 55: Inconsistent endpoint inclusion with contains_point
**Function:** `busiest_point`  
**Line:** 55  
**Issue:** Uses `a <= s <= b` (includes endpoints) while contains_point uses `<` (excludes endpoints). Inconsistent semantic.  
**Concrete input:** busiest_point([[1, 3]]) checks if 1 is in [1, 3] with <=, but contains_point([[1, 3]], 1) returns False due to < operator  
**Mitigation:** Standardize to one convention across functions

### 9. All functions: No validation that start ≤ end
**Functions:** All  
**Issue:** No check that start ≤ end for each interval. Inverted intervals cause silent garbage results.  
**Concrete input:** `merge_intervals([[5, 1], [2, 3]])` processes without error despite [5, 1] being invalid  
**Mitigation:** Add assertion or validation for all interval inputs

