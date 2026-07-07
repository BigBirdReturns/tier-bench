# Task 01 — parse_duration

Write a single Python function:

```python
def parse_duration(s: str) -> int:
    ...
```

It converts a duration string to a total number of **seconds** (an `int`).

**Format.** One or more `<count><unit>` segments concatenated with no separators.
Units are `h` (hours), `m` (minutes), `s` (seconds). Rules:

- `count` is a non-negative base-10 integer (one or more digits).
- Units must appear in **descending** order: `h` before `m` before `s`.
- Each unit may appear **at most once**.
- At least one segment is required.

**Valid examples**

| input | output |
|---|---|
| `"1h30m"` | `5400` |
| `"90m"` | `5400` |
| `"2h"` | `7200` |
| `"45s"` | `45` |
| `"1h30m15s"` | `5415` |
| `"0s"` | `0` |
| `"100h"` | `360000` |

**Invalid input → raise `ValueError`.** This includes (non-exhaustive): empty
string; unknown units (`"1x"`, `"1d"`); non-integer counts (`"1.5h"`, `"1,5h"`);
a unit with no count (`"h"`, `"hm"`); a count with no unit (`"10"`); repeated
units (`"1h1h"`, `"1h2h"`); units out of order (`"30m1h"`, `"15s30m"`); negative
numbers (`"-1h"`); any whitespace (`"1h "`, `" 1h"`, `"1h 30m"`); uppercase units
(`"1H"`); non-string types are out of scope (assume `s` is always a `str`).

Return the function only. No prose, no markdown fences, no `print`, no tests.
