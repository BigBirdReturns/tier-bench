# t_novel_02 — digit-pattern matcher

Implement a matcher for a tiny pattern language over **digit strings**.

## What you must submit

A Python module defining, at top level:

```python
def match(pattern: str, s: str) -> bool:
    """True iff s (a string of digits, possibly empty) matches pattern in full."""
```

## The pattern language

A pattern is a sequence of atoms, matched left to right against the whole of
`s` (no partial matches). The atoms:

- a digit `0`–`9` — matches exactly that digit
- `?` — matches any single digit
- `*` — matches any sequence of zero or more digits
- `[a-b]` where `a` and `b` are digits — matches a single digit `d`
  such that `a <= d <= b`

That is the complete semantics. Every atom except `*` consumes exactly one
digit of `s`; `*` consumes zero or more. The whole string must be consumed for
a match.

## Input guarantees

- `pattern` is always syntactically well-formed: `[` is always followed by
  exactly `digit`, `-`, `digit`, `]`; no other bracket or dash forms appear.
  You never need to reject a pattern.
- `s` consists only of digits `0`–`9` and may be empty.
- `len(pattern) <= 40`, `len(s) <= 40`.

## Examples

- `match("123", "123")` → `True`
- `match("1*9", "10009")` → `True` (the `*` absorbs `000`)
- `match("1*9", "19")` → `True` (the `*` absorbs nothing)
- `match("[2-7]", "5")` → `True`
- `match("[2-7]", "8")` → `False`
- `match("?", "")` → `False` (`?` must consume a digit)
- `match("*", "")` → `True`

Your module will be evaluated on inputs beyond these examples. Implement the
stated semantics exactly.
