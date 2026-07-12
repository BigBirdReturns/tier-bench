# burn_log.jsonl — provenance and reading rules

Input to `experiments/breadth/quota.py` (the self-calibrating quota gauge):
`spend` rows accrue to the open window; a `limit_hit` closes it. SAFE = the
smallest completed window; UNMEASURED until one closes.

**v2 (2026-07-12): the driver lane is now counted.** v1 logged solver-subagent
tokens only; extracting driver-session usage from the main transcript showed
the driver is **~97% of real burn** (window 1: 5.87M driver vs 0.19M solver
new tokens). Rows carry `lane: driver` or are solver trial rows; both count
toward the window.

Measured windows (new tokens = input + output + cache_write; cache reads
excluded — a known refinement, they bill ~0.1x):

| window | span (operator-attested walls) | solver | driver | total |
|---|---|---|---|---|
| 1 | 07-11T06:50Z → 07-12T08:03Z | 191,079 / 18 calls | 5,874,393 / 318 turns | ~6.07M |
| 2 | 07-12T08:03Z → 07-12T20:04Z | 0 (driver-only work) | 2,064,269 / 117 turns | ~2.06M |

Caveats, honestly held:

- **Wall attestation**: window boundaries are the operator's post-wall returns
  in the transcript. Window 1 may span unrecorded intermediate walls, which
  would OVERSTATE it — so treat SAFE (min) as optimistic and checkpoint early.
- **Lanes share one wall** here because the subscription pools them; if pools
  split by model, gauge per-lane (rows carry enough to re-bucket).
- The underlying evidence is the session/subagent transcripts; this file is an
  instrument reading, not a sealed ledger.

Current reading (2 samples): **SAFE ≈ 2.06M new tokens (~117 driver turns) per
window; checkpoint at ~1.65M.** The practical lesson stands confirmed: fitting
runs into quota quarters is driver-context discipline, not solver-count capping.
