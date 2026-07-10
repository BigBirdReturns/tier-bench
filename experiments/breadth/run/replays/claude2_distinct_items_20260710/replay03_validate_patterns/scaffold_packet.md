
## Rule commitments (hold these; do not re-derive)

- escape-inside-class malformed-vs-non-match boundary: **inside a character
  class, a backslash is a literal member (and a legal range endpoint), not an
  escape prefix**. Outside a class, backslash is an escape prefix. Hold this
  as a fixed rule interpretation — do not second-guess it mid-solve.
