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

## v3 (2026-07-13): rows self-write, and windows are per-account-tier

**Self-updating.** `experiments/breadth/hooks/session_burn_hook.py` (wired as a
`Stop` + `SessionEnd` hook in `.claude/settings.json`) now appends the driver-lane
`spend` row automatically — no more hand-extraction. It reads the session's own
transcript incrementally (byte-offset state in the gitignored `.burn_state/`),
sums assistant-row new tokens (in+out+cache_write), and UPSERTs one row keyed by
`session` (`auto: true`), so firing every turn still yields exactly one accurate
row per session and an abrupt container reclaim keeps the last total. It never
writes a `limit_hit`: closing a window is an operator-attested act, not automatic.

**Account tier is now a first-class dimension.** A **Plus** wall and a **Max20x**
wall are *different meters* — pooling their windows makes SAFE meaningless. Auto
rows carry `account` (from `$TIER_BENCH_ACCOUNT`, set per-checkout in the
gitignored `.claude/settings.local.json`). Gauge one tier with
`python -m experiments.breadth.quota burn_log.jsonl --account max20x`; the
default (no `--account`) still pools everything and reproduces the 2.06M reading.

- **Windows 1–3 above are Plus-lineage and untagged** (they predate tagging). A
  `--account`-filtered gauge *excludes* untagged rows rather than guess their
  tier, so the Plus SAFE≈2.06M is only visible in the pooled (unfiltered) gauge.
- **The Max20x gauge starts empty by design** — UNMEASURED until this account
  closes its first `limit_hit` window. That is the honest state, not a bug:
  Max20x's allotment is larger and has never been walled here, so there is no
  sample yet. Record a `limit_hit` when this account hits its wall to seed it.
