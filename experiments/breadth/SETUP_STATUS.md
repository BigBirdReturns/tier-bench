# Setup Status — Ready for Upcoming Fable Runs

**Date:** 2026-07-13
**Status:** ✅ READY FOR FABLE RUNS

## Sanity Checks (All Passing)

```bash
✅ python experiments/breadth/smoke.py
   → grade→ledger→map spine wired and green

✅ python experiments/breadth/breadth_tasks.py
   → 12 valid hidden-grader tasks identified (6 tier-uplift + 6 almanac/ossrf)
   → no ambiguity about the valid task set
```

## Toolbelt Complete

All required tools and docs are in place:
- ✅ `smoke.py` — keyless spine verification
- ✅ `breadth_tasks.py` — valid (hidden-grader) task set
- ✅ `ledger.py` — per-call telemetry + reconciliation
- ✅ `escalate.py` — residual discovery
- ✅ `rungs.py` — effort ladder
- ✅ `limit.py` — quota approach decision packet
- ✅ `adapt.py` — FREE/GATED gate
- ✅ `RUNBOOK.md` — two-phase protocol
- ✅ `LESSONS.md` — hard rules from the first run

## Current State Summary

**Settled Tasks: 9**
- task01_parse_duration (haiku, 3/3)
- task06_select (haiku, 3/3)
- t3_parse_duration_004 (haiku, 3/3)
- t4_plan_decomposition_001 (haiku, 3/3)
- task02_wildcard (sonnet-5@low, 3/3 — first measured model-separation)
- task09_pattern_class (haiku, 3/3)
- task10_topo_endmin (haiku, 3/3)
- almanac_exception_class_001 (haiku, 3/3)
- almanac_record_binding_001 (haiku, 3/3)

**Escalated & cleared (2026-07-13):**
- almanac_rule_boundary_001 — haiku 1/3 → **fable@low 3/3** (hidden 14/14 ×3). The
  lichun/jieqi solar-boundary residue, second measured model-separation (joins
  task02). Effort-before-access held: lowest Fable rung, no access spend, no Opus solve.

**Unstable (Non-Wall, non-frontier):**
- task08_select_exchange (haiku, 4/5 — procedural domain-bounds miss, cheap-trial territory)
- replay04_count_matches (haiku+packet, 1/3 — characterized scaffold-transfer depth limit)

**Open frontier residual: 0**
**Last Decision (2026-07-13):** DO NOT ESCALATE further — the one genuine judgment
residue is now cleared at fable@low; nothing walls; access was never touched.

## Historical Budget

- **Total spend to date:** $6.68 USD
- **Real-billed Fable:** $4.31 USD (earlier calibration runs)
- **Current quota:** Fresh for upcoming runs

## What to Expect

Per LESSONS.md and ROADMAP.md:

1. **If hidden-grader floor clears everything again:** report "floor wins" + the finding (novel-reasoning tasks defused by spec wording). Do NOT spend frontier tokens re-confirming a cleared floor (rule 2).

2. **If a wall emerges:** walk the effort ladder from fable@low upward (rule 3). Only escalate at real walls (all K=3 fails or 0/3).

3. **Golden path:** floor clears most → residual goes to fable@low → 3/3 clears residual → seal → report. Cost: cheap + fable@low.

4. **Efficiency:** run sequentially from constant cwd to exploit 1h prompt cache (rule 7). Give solver only spec + visible tests + target file (rule 7).

## Next Steps

Read in order when starting a run:
1. `experiments/breadth/LESSONS.md` (hard rules)
2. `experiments/breadth/RUNBOOK.md` (protocol)
3. Follow the paste-prompt in `experiments/breadth/FABLE_KICKOFF.md`

Then execute:
```bash
# Sanity (this is already passing, shown above)
python experiments/breadth/smoke.py
python experiments/breadth/breadth_tasks.py

# Phase 1: Floor (cheap, parallel K=3)
# → Phase 2: Residual escalation (effort ladder if needed)
# → Phase 3: Seal (append to known_corner.jsonl, report)
```

---

**Git state:** branch `claude/fable-runs-setup-wgph5h` is clean and ready.
**All tools:** verified working, sanity checks green.
**Ledger state:** reconciled, no missing receipts.

✅ This repo is ready for the upcoming Fable runs.
