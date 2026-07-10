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
| task02_wildcard | **settled at sonnet-5@low** | haiku 3/5 (judgment edge) -> sonnet@low 3/3 hidden 10681/10681, real ~$0.23/trial; first measured model-separation (layer model-ladder-task02-20260708) |

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

**Transport rule (learned from PR #44 trial-2, see pr44_trial2_adjudication.md):
have the model answer with the RAW function only** — starting at
`def wildcard_match(`, no JSON wrapper, no code fence. The JSON-lines transport
collapsed backslash escapes and turned three probable passes into unloadable
sources; ingest now classifies such rows as transport errors, never fails.

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

## Forward plan (the hypothesis tests — full ledger in /HYPOTHESES.md)

1. Operator: 3 clean GPT-5.5 task02 captures (raw-function transport) — closes
   the cross-provider comparison on the measured crack.
2. Freeze the task02 edge-family invariant table (operator review — gated),
   then build the 8 probes and run haiku/sonnet/GPT/fable-low at K=3: the
   first real test of H6 (frontier residue = judgment at boundaries).
3. Almanac boundary vectors (synthetic, PII-free) as the second judgment
   family.
4. Re-axis models.json: measured settled_floor + judgment_residue fields
   where rows exist; tier_ceiling stays declared elsewhere.
5. Fable medium→max: DO NOT RUN until a wall exists.

## Fable runway → see /ROADMAP.md (the say-go runway)

The full executable arc now lives in **`/ROADMAP.md`**. Turn high effort on, say
**"go"**, and that file is the only thing to read — every next PR is specced
there (files, schema, acceptance, and the Fable-vs-cheap spend split) so no
frontier token is burned re-deriving the plan.

Live state (mirror of ROADMAP STATE — arc items are keyed by content, ARC-x,
never by predicted GitHub PR number; the counter is shared with parallel
sessions and got consumed, #48–#54, on Jul 9):

1. **AXM provenance layer — DONE / merged** (PR #47): source ledger, 7-primitive
   registry, `validate_primitives.py` guard wired into CI. The two model-authored
   sources (gpt-5.5-high ledger, gpt-4o spectra) are recorded and author-named.
2. **ARC-A — Frontier capture ledger — NEXT, armed** (one branch, serial). Spec
   in ROADMAP.
3. **ARC-B — edge-family freeze + almanac hidden-knot corpus** — queued. Spec in
   ROADMAP. Absorbs the old runway items 2 (edge-family/almanac) and 3
   (adjudications). Authoring batch 1 (PR #54) is adjacent, not this item.

NOT Fable work (done or cheap): site/data plumbing, reruns of settled cells,
effort-matrix filling (LESSONS rule 2), doc edits, and the JSON/test/CI plumbing
inside each PR — route those to the floor per the ROADMAP spend split.

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
