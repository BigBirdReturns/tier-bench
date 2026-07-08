# NEXT_HANDOFF — continuation anchor (written before the Friday reset)

Whoever picks this up — fresh session, different model, post-reset — this file
plus `LESSONS.md` is the state. Do not re-derive anything below; diff against
it.

## Where the run stands (sediment layer: `k3-floor-20260708`)

| Cell | State | Evidence |
|---|---|---|
| task01_parse_duration | **settled** | 3/3, hidden 38/38, grades re-run by driver |
| task06_select | **settled** | 3/3 verified counterexamples (search-framing caveat noted in layer) |
| t3_parse_duration_004 | **settled** | 3/3 hidden-graded (tasks/ manifest, hidden_files mechanism) |
| t4_plan_decomposition_001 | **settled** | 3/3 incl. hidden semantic judge |
| task02_wildcard | **unstable** | 3/5; both failures the same escape-inside-class judgment edge — see `task02_edge_family.md` |

Open cells: **0**. Decision: **DO NOT ESCALATE** — no wall anywhere; Fable was
not turned on for the K=3 floor (frontier spend this layer: $0.00). task02 at
3/5 is noise-adjacent instability: the honest next spend is more *cheap*
trials or the edge-family probes, never a frontier token.

Budget: $6.68 of the $10 run quota (67%). Real-billed Fable total: $4.31 (all
from the earlier fable@low calibration). Everything else is shadow-estimated
subagent cost, labeled as such in `ledger.jsonl`.

## Subscription rows: still partial until raw captures are ingested

`subscription_ledger.jsonl` holds: task06 **pass** (locally verified
counterexample, candidate-hashed); task01 + task02 **partial** — operator
reported 38/38 and 10681/10681 but the frozen candidates were never saved, so
they stay below "pass" per the lane's own rule.

**Operator: to turn a UI answer into a receipt —**

```bash
# 1. generate the public packet (includes spec + subject/visible tests; never hidden files)
python experiments/breadth/subscription_run.py \
  --model-family "GPT-5.5" --intelligence "Instant" \
  --task-id task02_wildcard --trial 1 --out cap.json

# 2. paste cap.json's prompt_text into the UI at that exact selector state,
#    copy the model's raw answer into cap.json's "raw_output" field, then:
cat cap.json | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)))" >> captures.jsonl

# 3. ingest: extracts the candidate, RUNS THE HIDDEN GRADER LOCALLY, ledgers the row
python experiments/breadth/ui_capture_ingest.py captures.jsonl \
  --matrix-out experiments/breadth/run/ui_matrix.json
```

Priority captures when awake (per operator's own note): GPT-5.5 Instant /
Medium / High on **task02_wildcard** — that puts the frontier-vs-floor
comparison right on the one measured crack.

Lane self-test (no live model, $0): `python experiments/breadth/ui_capture_smoke.py`

## What was prepared overnight (this commit)

- `subscription_run.py` packet fix: public packet now carries `spec.md` +
  `subject.py` + `visible_tests.py` when present (task06 was unsolvable from
  spec alone); hidden artifact names scrubbed; hidden files never read.
- `ui_capture_smoke.py`: end-to-end lane test — valid capture must
  hidden-grade 38/38 at ingest, blocked cell must record
  `not_exposed_in_ui`, matrix must carry both. GREEN at commit time.
- `task02_edge_family.md`: the measured crack expanded into 8 proposed probes
  (proposal only — no new hidden graders until the invariant table is frozen
  and reviewed; adapt.py gates that).
- `experiments/almanac/DESIGN.md` "Next" section: the almanac lens family
  TODO — synthetic hidden vectors around lichun/jieqi/tz/cusp/anchor/master
  boundaries. PII stays out of the repo; no benchmark claim made.

## Standing rules (short form — full text in LESSONS.md)

Map only hidden-grader tasks (`breadth_tasks.py` prints the valid set).
Honor DO NOT ESCALATE. Effort before access; K-of-K is a ceiling, one miss is
noise. Re-run every hidden grade yourself. K=1 is not settled. Trim solver
context. Adapt freely, never self-grade. Reconcile or don't trust it.
Sediment is append-only.

## PR state

Everything above lives on `claude/setup-algstb` = **PR #42** (carries merged
PRs #39/#41 + the #41 ledger crash fix + the K=3 floor layer + almanac +
overnight prep). Merging #42 lands all of it; GitHub will auto-mark #39/#41
merged (their head commits are in this branch's history).
