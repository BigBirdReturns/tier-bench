# Answer key — task 03 (PRIVATE, never shown to solvers or the loop)

7 planted bugs in `subject.py`, by subtlety. A candidate "finds" a bug if its
report names the right location/mechanism (not just vibes).

| # | line | bug | subtlety | trigger |
|---|---|---|---|---|
| B1 | 7,9 | `history=[]` mutable default argument — history persists across calls, so the "running" average accumulates every sample ever passed, across unrelated calls | subtle-med | `running_average(1); running_average(2)` → 1.5, not 2.0 |
| B2 | 15 | `values.sort()` mutates the caller's list in place (unexpected side effect) | med | caller's list is reordered after `median(x)` |
| B3 | 25 | division by `old` with no zero guard → `ZeroDivisionError` when `old == 0` | easy-med | `percent_change(0, 5)` raises |
| B4 | 28–35 | `dedupe` never calls `seen.add(x)`, so `seen` stays empty and nothing is removed — returns the input unchanged | easy | `dedupe([1,1,2])` → `[1,1,2]` |
| B5 | 40 | off-by-one: `range(len(values) - k)` should be `range(len(values) - k + 1)` — the last window is never yielded | subtle | `list(moving_window([1,2,3], 2))` → `[[1,2]]`, missing `[2,3]` |
| B6 | 49 | bare `except:` swallows everything (incl. KeyboardInterrupt/SystemExit); and after exhausting attempts `retry` returns `None` silently instead of re-raising | subtle | a persistently failing `fn` → silent `None`, no signal |
| B7 | 57 | division by zero in `normalize` when all values are equal (`hi == lo`) | subtle | `normalize([5,5,5])` raises `ZeroDivisionError` |

`top_k` is CLEAN — no bug. A candidate that flags it is over-reporting (noted but
not penalized in the base score; tracked as a false-positive signal).

Scoring: N of 7 correctly identified. Partial credit (0.5) if the location is
right but the mechanism is vague/wrong.
