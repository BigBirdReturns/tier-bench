# Edge-family engagement 1 — $0, 11 candidates, one boundary found

All 11 existing task02 candidates profiled against the 8 probe groups
(verdicts frozen from tier-uplift's hand-verified reference — no new grading
authority). Full table reproducible: `python edge_grade.py <candidates...>`.

| Cohort | malformed-class | escaped-range | other 6 groups |
|---|---|---|---|
| haiku pass-candidates (3) | ok | ok | ok |
| haiku fail-candidates (2) | 3/5 wrong | 3/4 wrong | ok |
| sonnet@low (3) | ok | ok | ok |
| GPT-5.5 derived repairs (3, not receipts) | ok | ok | ok |

**Finding: the residue is ONE rule, not eight edges.** Both failing candidates
misjudge the same thing — *inside a character class, backslash is a literal
(and a legal range endpoint); outside, it is an escape prefix.* That single
choice cascades into exactly the two groups that touch in-class backslashes.
The other six designed boundaries (negation, literal hyphen, literal `]`,
trailing escape, escapes outside classes) are settled even at the haiku floor
— nobody cracks them.

Sharpened H6: the frontier residue on this task is a single binary rule
commitment. haiku commits correctly ~3/5 of the time; sonnet@low and GPT-5.5
(derived) commit correctly every time observed. Discriminating surface: 1 of
8 probes. Next escalation of the family should hunt rules of this shape
(implicit semantics choices a spec constrains but does not spell out), not
more surface variants of settled edges.
