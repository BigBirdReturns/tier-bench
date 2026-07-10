# task02_wildcard — the edge family, FROZEN as reviewed invariants

> **Freeze record (2026-07-10).** Closure authority: the operator's ARC-B
> authorization; reviewer: the driver session of 2026-07-10. Verdict source:
> every verdict below is derived MECHANICALLY from the settled tier-uplift
> `hidden_oracle.py` reference implementation (hand-verified, sediment layer
> k3-floor-20260708) — no verdict is anyone's opinion. Probes in the frozen
> table may back future hidden graders; any probe or verdict NOT in the table
> remains proposal-only and cannot become a grader (adapt.py discipline).

## The frozen invariant table (pattern, text → oracle verdict)

| Pattern | Text | Verdict | Invariant it pins |
|---|---|---|---|
| `[abc` | `a` | ValueError | unclosed class is malformed |
| `[\]` | `]b` | False | in-class `\` is a literal member; class never closes on content — valid, non-matching |
| `[\]` | `]]` | False | same |
| `[\]` | `\` | True | the literal backslash member matches a backslash |
| `[\*]` | `*` | True | `\` and `*` are two ordinary members inside a class |
| `[\*]` | `\` | True | same |
| `[\*]` | `a` | False | same |
| `[a\-z]` | `-` | False | in-class `\` is a legal RANGE ENDPOINT: members are `a` + range `\`..`z`; `-` (0x2D) is outside |
| `[a\-z]` | `b` | True | `b` is inside `\`..`z` |
| `[a\-z]` | `\` | True | endpoint inclusive |
| `a\` | `a` | ValueError | trailing escape (outside class) is malformed |
| `[!]` | `x` | ValueError | `!` consumes the negation slot; the class is then unclosed |
| `[!a]` | `b` | True | negation |
| `[!a]` | `a` | False | negation |
| `[-a]` | `-` | True | leading hyphen is literal |
| `[a-]` | `-` | True | trailing hyphen is literal |
| `[a-]` | `a` | True | same |
| `[]a]` | `]` | True | first-position `]` is literal |
| `[]a]` | `a` | True | same |
| `[]a]` | `b` | False | same |

One rule generates the whole backslash column — **inside a character class,
`\` is a literal (and a legal range endpoint); outside, it is an escape
prefix** — which is exactly the residue the capture ledger priced at $0.6805
and the crossing event replayed at the floor 5/5.

---

## Original proposal record (measured basis, kept verbatim below)

## What was measured (layer k3-floor-20260708)

`task02_wildcard` is **3/5 at the haiku floor** — the only non-settled cell.
Both failures are the SAME edge, twice, independently:

```
FAIL ('[\]', ']b'): raised ValueError, want False
FAIL ('[\]', ']]'): raised ValueError, want False
```

An escape-inside-character-class pattern that the oracle treats as a **valid
pattern that simply doesn't match**, which two of five candidates judged
**malformed** (ValueError). The three passing candidates got it right
(10681/10681).

## Classification: judgment-boundary residue, not spec coverage

This is not a missing rule the spec forgot to state — it is a *boundary
between two stated rules* (what is malformed vs. what merely fails to match)
applied to a pathological input. Richer specs don't fix it; the model must
*decide* which rule governs. That makes it the first measured floor residue of
the kind LESSONS rule 4 predicts the frontier gap is made of — and worth
probing as a family, not a one-off.

## Proposed neighboring probes (same daylight design: visible spec, hidden decisive cases)

| Probe | The judgment being isolated |
|---|---|
| malformed class vs valid non-match | `[` unterminated (malformed) vs `[\]` (valid, non-matching) |
| escaped literal inside class | `[\*]` — does `\*` inside a class mean literal `*`? |
| escaped range boundary | `[a\-z]` — literal hyphen via escape vs range |
| trailing escape | pattern ending in a bare `\` — malformed or literal? |
| class negation edge | `[!]` / `[!a]` — negation marker vs literal `!` as only member |
| literal hyphen edge | `[-a]`, `[a-]` — hyphen at edges is literal |
| literal closing bracket edge | `[]a]` — first-position `]` is literal |
| parser rejection vs matcher rejection | same inputs asked two ways: "is this pattern valid?" vs "does it match?" — measures whether the *framing* moves the judgment |

## Rules for promoting this to graded tasks

- Freeze the invariant FIRST: each probe's malformed-vs-non-match verdict
  table is written down and reviewed before any grader exists. **No new hidden
  graders until then** (this file is a proposal, not a grader — adapt.py
  classifies grader creation as gated work with a human in the loop).
- The tier-uplift `hidden_oracle.py` is untouched — it is settled sediment and
  the reference for the original cell.
- Grading stays candidate-vs-reference-oracle, exact equality, K=3.

## Status

FROZEN (2026-07-10) — see the freeze record at the top. Historical basis: 5 trials in
`run/ledger.jsonl` (task02_wildcard, 2026-07-08), sediment layer
`k3-floor-20260708` in `run/known_corner.jsonl`.
