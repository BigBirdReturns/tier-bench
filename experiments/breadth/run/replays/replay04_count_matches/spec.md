# count_matches

Write a single Python function in `solution.py`:

```python
def count_matches(pattern: str, words: list[str]) -> int:
    ...
```

Return how many of `words` the wildcard `pattern` matches ENTIRELY. Syntax:
`*` any sequence (incl. empty); `?` exactly one char; `[...]` one char from a
class (ranges by ASCII, low > high malformed → ValueError; leading `!` negates;
`]` literal as first member; `-` literal at the edges; unclosed class malformed
→ ValueError); `\` escapes the next character making it literal (trailing `\`
malformed → ValueError; escaping applies outside character classes). A
malformed pattern raises ValueError (never returns a count).
