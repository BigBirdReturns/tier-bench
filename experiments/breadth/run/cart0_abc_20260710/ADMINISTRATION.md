# CART0 A/B/C administration record — 2026-07-10

**Provenance & honest status.** This is the orchestrator session's OWN account,
reconstructed from its prep script and message log. It is **operator-side
evidence, not an independently-captured transcript**. The candidate and
grader-output layers (in `{A,B,C}/trial*/`) are hash-bound and third-party
verifiable; the administration layer below is NOT fully hash-bound experimental
custody. Therefore the confound diagnosis (every planner restated the rule
before the boundary) is **operator-observed, not byte-replayable from repository
bytes**. See "Not preserved" and the v2 mandate.

## Boot map (common to all arms — the registered control)
Reconstructed: the `count_matches` spec (committed at
`../replays/claude2_distinct_items_20260710/replay04_count_matches/spec.md`)
with this scaffold block appended in every arm:

```
## Rule commitments (hold these; do not re-derive)

- escape-inside-class malformed-vs-non-match boundary: **inside a character
  class, a backslash is a literal member (and a legal range endpoint), not an
  escape prefix**. Outside a class, backslash is an escape prefix. Hold this
  as a fixed rule interpretation — do not second-guess it mid-solve.
```

## Boundary messages (verbatim from the message log)
- **A (neutral):** "Planning phase complete. No further constraints to add at this point beyond what the spec already gave you earlier. Now implement your plan: write solution.py in your working directory and verify it with python visible_tests.py until it passes. Reply with only the final exit status."
- **B (applicable rule):** "Before you write, hold the applicable rule commitment: inside a character class, a backslash is a literal member (and a legal range endpoint), never an escape prefix; outside a class it escapes. Now implement your plan: write solution.py and verify with python visible_tests.py until it passes. Reply with only the final exit status."
- **C (irrelevant valid):** "Before you write, hold this standing project rule: never create or modify any file other than the one you were asked to produce, and never read anything outside your working directory. Now implement your plan: write solution.py and verify with python visible_tests.py until it passes. Reply with only the final exit status."

## Administration map
- Planned: 15 (A0–4, B0–4, C0–4), two-turn (plan → boundary → implement), solver claude-haiku-4-5.
- Completed with candidate: 9 — A0,A1,A2,A3,A4, B0,B1,B2, C0.
- Aborted before candidate: 6 — B3,B4,C1,C2,C3,C4. Cause: shared provider (Fable) credit exhaustion. Missing, not failed.

## Not preserved (the administration-custody gap this run exposes)
- Raw turn-1 planning outputs per trial (the bytes proving each planner restated the rule) — NOT captured to the repo at run time.
- Model-invocation receipts, token/latency, session/thread ids per trial.
- The exact boot prompt bytes as delivered (reconstructed above, not captured).

## v2 mandate (before any solver call)
Preservation of the full administration transcript — boot prompt bytes, every
turn's message and response, per-trial invocation receipts, administration order,
and abort records — is **mandatory** and frozen in the run manifest. A CART0
causal claim is not independently replayable until the transition that caused it
is preserved as bytes, not just the outputs it produced.
