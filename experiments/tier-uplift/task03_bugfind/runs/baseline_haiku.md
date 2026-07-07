# Correctness Bugs in metrics.py

1. **Line 7, running_average**: Mutable default argument `history=[]` creates a shared list across all function calls, causing all invocations to accumulate samples into the same history instead of maintaining separate histories.

2. **Line 15, median**: Function mutates the input list by calling `values.sort()`, which is an unexpected side effect for a function that should only compute a value.

3. **Line 16, median**: Empty input causes IndexError when accessing `values[0]` on line 20 (even-length case tries to access the first element of an empty list).

4. **Line 25, percent_change**: No handling for division by zero when `old=0`, causing ZeroDivisionError instead of graceful error handling.

5. **Line 33-35, dedupe**: The `seen` set is never updated with encountered values; `x` should be added to `seen` after the check, causing the function to fail to remove any duplicates (all elements pass the not-in-seen check repeatedly).

6. **Line 40, moving_window**: No validation that `k > 0`; when `k <= 0` the function yields empty slices or unexpected results instead of raising an error or enforcing valid window size.

7. **Line 48-50, retry**: Silent failure—if all retry attempts raise exceptions, the function returns `None` without any indication of failure, leaving the caller unaware whether execution succeeded or all retries failed.

8. **Line 57, normalize**: No handling for division by zero when all values are identical (when `hi == lo`), causing ZeroDivisionError on the denominator `(hi - lo)`.
