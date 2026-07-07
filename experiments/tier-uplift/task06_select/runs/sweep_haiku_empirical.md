# Empirical Testing of select() Function

## Summary

Empirical testing of the `select()` function found a **counterexample** where the implementation disagrees with a brute-force reference implementation.

The function uses a greedy algorithm that selects the top-k most valuable items, then attempts to repair violations of the weight constraint by performing single-item swaps. This approach **does not always find the global optimum**, particularly when no single swap from the greedy solution satisfies the constraint but other valid combinations exist.

## Test Methodology

- **Reference Implementation**: Brute-force enumeration of all k-combinations, filtering to those with weight sum divisible by 3, returning the maximum value
- **Test Cases**: 5,000 random trials with:
  - n: 3 to 6 items
  - k: 1 to n
  - Values: 1-9
  - Weights: 0-4
- **Result**: Counterexample found on trial #276

## Counterexample Details

**Input:**
- Items: `[(3, 1), (5, 0), (4, 4), (5, 0), (5, 1), (9, 4)]`
- k: 3

**Analysis:**
The function's greedy algorithm selects indices [5, 1, 3] (items with values 9, 5, 5), which have:
- Total value: 19
- Total weight: 4 + 0 + 0 = 4 (4 % 3 = 1, violates constraint)

The repair phase tries all single swaps but none satisfy the constraint (weight % 3 == 0), so the function returns `None`.

However, a valid combination exists: indices [2, 4, 5] with:
- Items: (4, 4), (5, 1), (9, 4)
- Total value: 18
- Total weight: 4 + 1 + 4 = 9 (9 % 3 = 0, satisfies constraint)

**Expected Result:** 18
**Actual Result:** None
**Discrepancy:** MISMATCH

## Valid Combinations for This Input
All combinations with weight % 3 == 0:
- {0, 2, 4}: value=12, weight=6
- {0, 2, 5}: value=16, weight=9
- {0, 4, 5}: value=17, weight=6
- {2, 4, 5}: value=18, weight=9 ← Maximum

COUNTEREXAMPLE: items=[(3, 1), (5, 0), (4, 4), (5, 0), (5, 1), (9, 4)]; k=3
