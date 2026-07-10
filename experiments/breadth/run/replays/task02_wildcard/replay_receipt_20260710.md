# Replay receipt — task02_wildcard via floor + scaffold packet (2026-07-10)

**The crossing event, measured.** The first validated replay of the
`task02_escape_class_boundary` capture: the cheap floor carrying the captured
rule commitment did the work that previously required a sonnet-priced call.

## Protocol (docs/frontier-capture.md replay protocol)

- Packet: `scripts/emit_scaffold.py --task task02_wildcard` rule commitment
  (in-class backslash is a literal, not an escape prefix) appended to the same
  trimmed task packet the bare-floor baseline used (spec + visible tests).
- Solver: claude-haiku-4-5 subagents, one fresh instance per trial, K=5,
  forbidden from reading repo files.
- Grade: `experiments/tier-uplift/task02_wildcard/hidden_oracle.py`, re-run by
  the driver on every returned candidate (never the solver's self-report).

## Result

| Trial | Candidate | Hidden oracle | Exit |
|---|---|---|---|
| 0 | `replay01_candidate.py` | 10681/10681 | 0 |
| 1 | `replay02_candidate.py` | 10681/10681 | 0 |
| 2 | `replay03_candidate.py` | 10681/10681 | 0 |
| 3 | `replay04_candidate.py` | 10681/10681 | 0 |
| 4 | `replay05_candidate.py` | 10681/10681 | 0 |

**floor + packet: 5/5.** Bare-floor baseline (layer `k3-floor-20260708`,
no packet): **3/5**, both misses the captured rule. The artifact transfers the
judgment.

Re-verify any row:
```
python experiments/tier-uplift/task02_wildcard/hidden_oracle.py \
  experiments/breadth/run/replays/task02_wildcard/replay01_candidate.py
```

## Honest accounting

- This run replays the **same task instance** five times. That is ONE reuse
  (one unit of work done via the cheap path), counted as **1 validated
  replay** — the K=5 is reliability evidence for the crossing comparison, not
  five reuses. Minting 5 receipts from 1 work item would be gaming the ledger.
- Break-even (projected 4) therefore needs **3 more replays on DISTINCT
  task02-class work items** (edge-family variants, almanac rule-boundary
  knots — ARC-B supplies them).
- Costs are shadow-estimated (subagent token estimates; no provider bill):
  5 trials, ~221k total subagent tokens, ~$0.31 est. Rows tagged
  `run=crossing-event-task02-20260710` in `run/ledger.jsonl`.
- Caveat: the bare-floor baseline's packet wording (Jul 8 session) is not
  byte-identical to this run's packet-minus-scaffold; the only *designed*
  difference is the scaffold block, but prompt-wording drift is a possible
  confound. A same-session A/B (bare vs packet, same wording) would remove it;
  recorded as the next sharpening, not claimed away.
