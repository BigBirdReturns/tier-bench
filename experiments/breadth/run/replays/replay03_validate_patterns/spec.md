# validate_patterns

Write a single Python function in `solution.py`:

```python
def validate_patterns(patterns: list[str]) -> list[bool]:
    ...
```

For each wildcard pattern, return True if it is well-formed, False if malformed.
Syntax: `*` (any sequence), `?` (one char), `[...]` character classes (ranges by
ASCII — low > high is malformed; leading `!` negates; `]` literal if first
member; `-` literal at edges; unclosed class is malformed), and `\` escapes the
next character outside classes (a trailing `\` with nothing after is malformed).
