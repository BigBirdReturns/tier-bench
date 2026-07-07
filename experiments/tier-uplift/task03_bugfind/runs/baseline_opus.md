# Correctness bugs in metrics.py

1. **Line 7, `running_average`** — Mutable default argument `history=[]` is shared across all calls, so the "running" history accumulates every sample ever passed in any invocation; triggers on the second and later calls when no explicit history is supplied.

2. **Line 9-10, `running_average`** — Because it always appends and divides by `len(history)`, callers cannot get an independent average; any two logically separate streams contaminate each other whenever the default history is used.

3. **Line 15, `median`** — `values.sort()` mutates the caller's list in place (unintended side effect), reordering the input the caller may still need.

4. **Line 16-20, `median`** — Empty input crashes: `n = 0`, `mid = 0`, `n % 2 == 1` is false, and `values[0] + values[-1]` raises `IndexError` on the empty list.

5. **Line 25, `percent_change`** — Divides by `old` with no guard, raising `ZeroDivisionError` (or producing inf for floats) whenever `old == 0`.

6. **Line 33-34, `dedupe`** — `seen` is never updated (`seen.add(x)` is missing), so `x not in seen` is always true and every element is appended; duplicates are never removed, defeating the function's purpose for any input containing repeats.

7. **Line 40, `moving_window`** — `range(len(values) - k)` stops one short: it omits the final window; e.g. `values` of length 5 with `k=2` yields only 3 windows instead of 4. Should be `range(len(values) - k + 1)`.

8. **Line 40, `moving_window`** — When `k == len(values)` the loop range is `range(0)` and yields nothing even though exactly one full-length window exists; and when `k > len(values)` the negative argument yields nothing (acceptable) but the off-by-one still hides the boundary case.

9. **Line 49, `retry`** — Bare `except:` swallows every exception including `KeyboardInterrupt` and `SystemExit`, making the process uninterruptible during retries.

10. **Line 44-50, `retry`** — After all `attempts` fail, the function falls off the end and silently returns `None` instead of raising, so callers cannot distinguish a genuine `None` result from total failure; triggers whenever every attempt raises.

11. **Line 55-57, `normalize`** — When all values are equal, `hi - lo == 0` and the comprehension raises `ZeroDivisionError`; triggers on any constant input (including a single-element list).

12. **Line 55, `normalize`** — Empty input crashes at `min(values)` with `ValueError`.

13. **Line 62, `top_k`** — A negative `k` (e.g. from an off-by-one caller) silently drops elements from the end rather than returning the top results, producing wrong output instead of an error.
