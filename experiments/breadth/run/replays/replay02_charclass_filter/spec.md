# charclass_filter

Write a single Python function in `solution.py`:

```python
def charclass_filter(cls: str, chars: str) -> str:
    ...
```

`cls` is one character-class token in wildcard syntax, e.g. `[abc]`, `[a-z]`,
`[!x]`. Return the characters of `chars` (in order, duplicates kept) that the
class matches. Class semantics:

- Lists characters: `[abc]` matches `a`, `b`, or `c`.
- Ranges by ASCII: `[a-z]`. A range whose low > high (e.g. `[z-a]`) is
  **malformed** → raise `ValueError`.
- A leading `!` negates the class.
- A literal `]` is allowed as the FIRST member: `[]a]` matches `]` or `a`.
- `-` as first or last member is a literal `-`.
- An unclosed class (no terminating `]`) is **malformed** → raise `ValueError`.
