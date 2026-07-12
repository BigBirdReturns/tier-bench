# Quota gauge — inferring the meter you don't get handed

**Problem.** A session never sees "tokens remaining." The operator can't easily
hand a number either. But runs still need to fit inside the allotment, and
`limit.py` needs a `quota` to park at 80% of.

**The gauge (operator's call): the intervals between limit-hits *are* the meter.**
The burn between two consecutive limit-hits is one empirical sample of the
allotment. `experiments/breadth/quota.py` turns those samples into a number:

- **SAFE** = the smallest completed window — what you can *count on* before the
  next wall. Plan against this.
- **LIKELY** = the median completed window — what you'll *typically* get.
- **UNMEASURED** until at least one window closes. Zero walls ≠ infinite quota;
  `fit_run` refuses to size quarters against a guess (absence is the answer).

## How a run feeds and uses it

1. **Log every trial's tokens** to a ledger (`ledger.py`) — close the
   "buffalo escaped" gap. `quota.per_trial_from_ledger(rows)` gives the mean
   *new* tokens/trial (input+output+cache_write; cache reads are ~0.1× and
   excluded). For the ARC-C almanac floor run that was **~9.5k new tokens/trial**
   (the 9 solvers together: ~85k new + ~323k cache-read — cheap; see
   `experiments/breadth/run/almanac_floor_arcc_20260711/ledger.jsonl`).
2. **Record a `limit_hit`** in a burn log whenever a wall is hit
   (`{"type":"limit_hit"}` after the run's spend rows). Each one closes a window
   and sharpens the gauge.
3. **Size the run into quarters**: `fit_run(n_trials, per_trial_tokens,
   quota_tokens=gauge.safe)` splits the work into 4 checkpoints. At each quarter
   boundary: **seal + ledger-log + gauge check, then continue.** If the run
   needs more than one window, the plan says how many walls to expect.

```
python -m experiments.breadth.quota burn.jsonl                 # print the gauge
python -m experiments.breadth.quota burn.jsonl --fit 9 --per-trial-tokens 9500
```

## The lever that actually matters

The solver fan-out (haiku/fable trials) is **cheap** — the 9 almanac solvers
cost less than a single large driver read. The expensive seat is the **driver
session** (long context, big file reads). So "fit in a quarter" is mostly
driver discipline: keep coordinator context lean (extract via targeted scripts,
don't re-read giant transcripts), not capping solver count. The gauge measures
whichever wall binds first — tokens or calls — and quarters against it.

## Status

`quota.py` + `tests/test_quota.py` (10 tests, in `breadth-durability` CI).
The live gauge is **UNMEASURED** until this session records its first
`limit_hit` window — by design. Once a wall closes, `fit_run` starts sizing
real quarters instead of illustrative ones.
