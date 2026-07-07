# Error-Handling & Silent-Failure Review: metrics.py

## Line 10: Unguarded Division in `running_average()`
**Issue:** Division by `len(history)` without checking if history is empty.
- If `running_average()` is called with an empty history and no sample has been appended, `len(history)` is 0, causing `ZeroDivisionError`.
- The mutable default argument `history=[]` compounds this issue — an initially empty history remains empty if the function is never called, leading to division by zero on first invocation.

## Line 25: Unguarded Division in `percent_change()`
**Issue:** `(new - old) / old * 100.0` performs division without checking if `old == 0`.
- If `old` is 0, raises `ZeroDivisionError`.
- No error handling to surface or prevent this failure.

## Line 49-50: Bare `except:` Clause in `retry()`
**Issue:** `except:` catches all exceptions, including `KeyboardInterrupt`, `SystemExit`, and other non-Exception types.
- Masks serious control-flow exceptions that should not be caught.
- Caller cannot distinguish between legitimate failure and fatal errors.

## Line 51: Silent Failure in `retry()` on All Attempts Exhausted
**Issue:** Function implicitly returns `None` if all retry attempts fail without catching an exception.
- Caller cannot determine if `None` is a legitimate return value or a sign that all attempts failed.
- No exception is re-raised; the failure is silently swallowed.

## Line 57: Unguarded Division in `normalize()`
**Issue:** `(hi - lo)` in denominator when all values are identical.
- If all values in the list are the same, `hi == lo`, causing `ZeroDivisionError` on division by 0.
- No guard condition or error handling.

## Line 55-56: Missing Error Handling for Empty `values` List
**Issue:** `min(values)` and `max(values)` raise `ValueError` if `values` is empty.
- No guard to check if the list is non-empty before calling min/max.
