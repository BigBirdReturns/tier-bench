# Code Review: intervals.py (DATA & TYPES Lens)

## Issues Found

| Line | Function | Issue | Concrete Input |
|------|----------|-------|-----------------|
| 16 | `merge_intervals()` | Condition excludes touching intervals. Docstring says touching (e.g. [1,2] and [2,3]) should merge, but `cur[0] < last[1]` is False when cur[0]==last[1]. Should be `<=`. | `merge_intervals([(1,2), (2,3)])` returns `[(1,2), (2,3)]` instead of `[(1,3)]` |
| 17 | `merge_intervals()` | Mutates interval tuple in-place (`last[1] = ...`). If input intervals are tuples (immutable), raises `TypeError: 'tuple' object does not support item assignment`. | `merge_intervals([(1,5), (3,7)])` crashes if intervals are tuples |
| 31 | `contains_point()` | Boundary comparison excludes endpoints. Docstring says "(endpoints included)" but condition `s < p < e` is strict inequality, excluding s and e. Should be `s <= p <= e`. | `contains_point([(1,3)], 1)` returns False instead of True |
| 55 | `busiest_point()` | Inconsistent boundary handling vs `contains_point()`. Uses `a <= s <= b` (includes endpoints) while `contains_point()` uses `s < p < e` (excludes endpoints). One should match the documented behavior. | `[(1,3), (1,2)]` at point 1: busiest_point includes point 1, contains_point excludes it |

## Summary

- **Critical**: merge_intervals fails on tuples (line 17) and doesn't merge touching intervals (line 16)
- **Critical**: contains_point excludes endpoints despite docstring promising inclusion (line 31)
- **Data consistency**: boundary inclusion semantics differ between functions

