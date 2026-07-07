# Code Review: intervals.py — STATE & EFFECTS

## Issue 1: Input mutation via aliasing in merge_intervals()

**Line:** 17 in `merge_intervals()`  
**Function:** `merge_intervals(intervals)`  
**Explanation:** Line 17 mutates `last[1]` (an alias into the input), corrupting the caller's original intervals.

**Trace:**
- Line 12: `s = sorted(intervals, ...)` creates new list but stores references to original interval objects
- Line 13: `merged = [s[0]]` stores reference to first input interval
- Line 17: `last[1] = max(last[1], cur[1])` mutates that reference

**Concrete input showing caller's data changing:**
```python
intervals = [[1, 3], [2, 5]]
result = merge_intervals(intervals)
print(intervals)  # Output: [[1, 5], [2, 5]]  — intervals[0] was modified!
print(result)     # Output: [[1, 5]]
```

The caller's `intervals[0]` changed from `[1, 3]` to `[1, 5]`.

---

## Issue 2: Appended elements are aliased to input in merge_intervals()

**Line:** 19 in `merge_intervals()`  
**Function:** `merge_intervals(intervals)`  
**Explanation:** Elements appended to `merged` are references to the sorted input list, not copies. Caller's input intervals may be modified by downstream code that mutates the returned list.

**Trace:**
- Line 12: `s = sorted(intervals, ...)` 
- Line 19: `merged.append(cur)` stores reference to `cur` from input
- Caller receives list with aliased references to original intervals

**Concrete input showing caller's data changing:**
```python
intervals = [[1, 3], [4, 6]]
result = merge_intervals(intervals)
result[0][1] = 999  # Mutate the returned result
print(intervals)    # Output: [[1, 999], [4, 6]]  — intervals[0] was modified!
```

The caller's `intervals[0]` changed due to aliasing in the return value.

---

## Issue 3: contains_point() endpoint logic contradicts specification

**Line:** 31 in `contains_point()`  
**Function:** `contains_point(intervals, p)`  
**Explanation:** The check `s < p < e` excludes endpoints, but the docstring states "endpoints included."

**Concrete counterexample:**
```python
contains_point([[1, 5]], 1)  # Returns False, but should return True (endpoint)
contains_point([[1, 5]], 5)  # Returns False, but should return True (endpoint)
```

Should be: `if s <= p <= e:` to honor the "endpoints included" contract.

*Note: This is not a mutation issue, but a specification violation that affects interval coverage checks.*
