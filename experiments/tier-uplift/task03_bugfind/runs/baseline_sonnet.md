# metrics.py — Correctness Bug Findings

1. **Line 7, `running_average`** — `history=[]` is a mutable default argument evaluated once at function-definition time, so every call that doesn't pass its own `history` shares and permanently accumulates into the *same* list across unrelated calls/streams, producing wrong running averages (including data left over from previous, logically unrelated uses of the function) for the entire life of the process.

2. **Line 15, `median`** — `values.sort()` sorts the caller's list in place (an unintended side effect that mutates the argument the caller passed in) instead of operating on a copy, silently reordering data the caller may still need.

3. **Lines 17–20, `median`** — for an empty input list (`n == 0`), `mid = 0` and `n % 2 == 1` is False, so execution falls into `return (values[mid] + values[mid - 1]) / 2`, which indexes an empty list and raises `IndexError` instead of handling/raising a clear error for empty input.

4. **Line 25, `percent_change`** — when `old == 0`, `(new - old) / old` divides by zero and raises `ZeroDivisionError`; there is no guard for the (very common) baseline-of-zero case.

5. **Lines 30–35, `dedupe`** — `seen.add(x)` is never called inside the loop, so `seen` stays empty forever and the `x not in seen` check is always True; the function therefore fails to remove any duplicates at all and just returns a copy of the input, silently violating its stated purpose for any input containing duplicates.

6. **Line 40, `moving_window`** — the loop uses `range(len(values) - k)` instead of `range(len(values) - k + 1)`, an off-by-one error that drops the final valid window; e.g. `moving_window([1,2,3,4,5], 5)` yields zero windows even though the whole list is one valid length-5 window, and any call with `k == len(values)` (or generally the last possible window position) silently loses that window.

7. **Line 40/41, `moving_window`** — no validation of `k`; if `k <= 0`, `range(len(values) - k)` still runs and `values[i:i+k]` yields degenerate/empty or nonsensical slices instead of raising a clear error, and if `k > len(values)`, `range()` silently produces an empty range rather than signaling that `k` is invalid.

8. **Lines 46–50, `retry`** — the bare `except:` catches *everything*, including `KeyboardInterrupt` and `SystemExit`, not just the exceptions the caller intended to retry on, so it can swallow process-control signals; additionally, if every attempt fails, the function falls off the end and implicitly returns `None` instead of raising (or re-raising the last exception), silently masking total failure and making it indistinguishable from a legitimate `None` result from `fn()`.

9. **Lines 55–57, `normalize`** — when all values are equal, `hi - lo == 0`, causing `ZeroDivisionError` for every element; there is no handling of this degenerate (but realistic, e.g. a constant-valued sample stream) case.

10. **Lines 55–56, `normalize`** — calling `normalize([])` raises `ValueError: min() arg is an empty sequence` (and likewise for `max()`), since there is no guard for empty input.

11. **Line 62, `top_k`** — no validation of `k`; a negative `k` silently falls through to Python's slice semantics (`sorted(...)[:k]` with negative `k` returns "all but the last `|k|`" elements) rather than raising an error or being treated as "0 results," so callers passing a negative `k` (e.g. from a miscalculated offset) get a plausible-looking but semantically wrong answer instead of a failure.
