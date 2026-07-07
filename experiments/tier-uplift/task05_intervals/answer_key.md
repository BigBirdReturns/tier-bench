# Answer key — task 05 (PRIVATE)

Bugs in `intervals.py`. **The lens set used on this task is the FROZEN generic
one (`../lenses.md`) — NOT tailored to these bugs.** One bug (B1) is a
deep-reasoning/algorithm-correctness bug (candidate weights-bound residual); the
rest are attention-level.

| # | line | bug | class | trigger (verified) |
|---|---|---|---|---|
| B1 | 41 | `max_non_overlapping` sorts by **start** (`x[0]`) — interval scheduling greedy is only correct sorted by **end** (`x[1]`). The whole algorithm is wrong, not one line. | **DEEP** (algorithm) | `max_non_overlapping([[1,100],[2,3],[4,5]])` → 1, correct is 2 |
| B2 | 16 | `merge_intervals` uses `cur[0] < last[1]`; touching intervals don't merge though the module docstring says they overlap → should be `<=` | attention | `merge_intervals([[1,2],[2,3]])` → `[[1,2],[2,3]]`, correct `[[1,3]]` |
| B3 | 17 | `merge_intervals` mutates the **caller's** interval sublists in place (`last[1] = ...`; `merged` holds references to the input lists) | attention/state | input `[[1,5],[2,8]]` becomes `[[1,8],[2,8]]` after the call |
| B4 | 32 | `contains_point` uses strict `s < p < e`, excluding endpoints, but the docstring says endpoints are included → should be `<=` | attention | `contains_point([[1,5]], 5)` → `False`, correct `True` |
| B5 | all | no function validates `start <= end`; an inverted interval silently yields wrong results | validation | `total_covered([[5,3]])` → `-2` (negative length) |

`busiest_point` (lines 54–62) is **CORRECT** — max overlap is always achieved at
some interval's start, so scanning starts suffices. Flagging it as buggy is a
**false positive** (precision signal, not scored).

Scoring: N of 5. B1 requires recognizing the *algorithm* is wrong (sort key),
not merely flagging the function. The boundary question: does haiku, under the
frozen generic sweep, catch B1 — or is B1 the weights-bound residual only the
higher tier gets?
