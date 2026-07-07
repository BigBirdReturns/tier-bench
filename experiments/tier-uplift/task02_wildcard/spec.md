# Task 02 — wildcard_match

Write a single Python function:

```python
def wildcard_match(pattern: str, text: str) -> bool:
    ...
```

Return `True` iff `pattern` matches the **entire** `text`. Both are `str`.

**Pattern syntax**

- `*` — matches any sequence of characters, including the empty sequence.
- `?` — matches exactly one character.
- `[...]` — a character class matching one character:
  - Lists characters: `[abc]` matches `a`, `b`, or `c`.
  - Ranges by ASCII: `[a-z]`, `[0-9]`. A range whose low > high (e.g. `[z-a]`)
    is **malformed** → raise `ValueError`.
  - Negation: a leading `!` negates the class — `[!abc]` matches any one
    character that is NOT `a`, `b`, or `c`.
  - A literal `]` is allowed as the **first** class member (right after `[`, or
    right after `[!`): `[]a]` matches `]` or `a`.
  - `-` as the last character before `]` is a literal `-`.
  - An unclosed class (no terminating `]`) is **malformed** → raise `ValueError`.
- `\` — escapes the next character, making it a literal (so `\*` matches a
  literal `*`, `\[` a literal `[`, `\\` a literal backslash). A trailing `\`
  with nothing after it is **malformed** → raise `ValueError`. (Escaping applies
  outside character classes.)
- Any other character matches itself literally.

**Examples**

| pattern | text | result |
|---|---|---|
| `*` | `""` | `True` |
| `a*c` | `abbbc` | `True` |
| `a*c` | `abbb` | `False` |
| `a?c` | `ac` | `False` |
| `[a-c]` | `b` | `True` |
| `[!a-c]` | `d` | `True` |
| `[]a]` | `]` | `True` |
| `\*` | `*` | `True` |
| `a[b-d]*z` | `acxyz` | `True` |

**Malformed pattern → `ValueError`:** unclosed class (`[abc`), trailing
backslash (`a\`), reversed range (`[z-a]`).

Return the function only — no markdown fences, no prose, no tests, no prints.
Matching must be anchored to the whole text (not a substring search).
