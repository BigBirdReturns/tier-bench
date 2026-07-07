# tier-uplift — can a cheap model, wrapped, reach the tier above?

**The claim under test:** the frontier edge is not (mostly) judgment — a cheap
model re-derives judgment on demand (see `../../data/control-results/`, and the
three horizon confounds logged in `LEDGER.md`). What a cheaper model lacks is
**carried state and selection**: it drops the contingent thread, and it can't
tell its own good output from its bad. A harness supplies both. So:

> Does `haiku + harness` match `sonnet` alone? Does `sonnet + harness` match `opus`?

Token efficiency is **not** the metric for the early passes — we spend freely to
find out whether the ceiling can be reached at all. Every run is logged in
`LEDGER.md` with its score, so the cost/quality trade can be read back later.

## Method

- **Substrate:** real model instances (subagents), so no API keys are needed.
- **Grading:** objective where possible. A task ships a `visible_tests.py` (the
  ONLY validator the harness may select against) and a stronger, hidden
  `hidden_tests.py` (never shown to any solver or loop) that produces the score.
  Daylight between the two is deliberate — the loop can only buy what visible
  selection can see; the hidden set says whether that bought real quality.
- **Baseline first:** each tier solves the task solo. If there's no gap, the task
  is useless and gets replaced.
- **Then the harness** wraps the cheap tier and we re-grade on the hidden set.

## The harness, built up pass by pass

Each pass adds one mechanism and we log whether it moved the hidden score:

1. **select** — best-of-N against `visible_tests.py` (turns "can't tell good from
   bad" into "keep the one that passes what we can see").
2. **repair** — feed the visible-test failures back for a fix (driver/hands).
3. **memory** — carry contingent state across steps via a sealed decision shard
   (`../../memory/`), so a multi-step task doesn't drop its own earlier choices.
4. **critic** — an independent pass that hunts for unhandled cases the visible
   tests miss, and proposes new checks (extends what selection can see).

## Tasks

- `task01_parse_duration/` — validation-heavy; edge cases (ordering, repeats,
  whitespace, non-integers) are where tiers separate. Objective grader.

See `LEDGER.md` for every run.
