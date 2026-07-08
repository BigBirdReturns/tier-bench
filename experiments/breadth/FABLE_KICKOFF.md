# Fable kickoff — paste this when quota resets

Paste the block below into the Fable/ultracode session (tier-bench pulled to latest
`main`). It points Fable at everything built this session and runs the firehose
efficiently, honestly, and without wasting your allotment.

---

```
You are the driver for a breadth-mapping run in this repo (tier-bench). Before doing
anything, read these in order and follow them:
  experiments/breadth/LESSONS.md      (hard rules — obey them)
  experiments/breadth/RUNBOOK.md      (the protocol)
  experiments/breadth/breadth_tasks.py, ledger.py, escalate.py, rungs.py, limit.py,
  adapt.py, smoke.py                  (your tools)

Then run, efficiently:

1. SANITY: `python experiments/breadth/smoke.py` (grade→ledger→map spine, $0). Then
   `python experiments/breadth/breadth_tasks.py` — the ONLY valid task set is what it
   prints (hidden graders). Never map the tasks/*.json set.

2. FLOOR (cheap, no Fable): solve each valid task with haiku subagents, K=3, giving
   the solver ONLY spec + visible tests + target (trim context — bloated context is
   the burn). Score with the HIDDEN grader. Then RE-RUN each hidden grader yourself
   and confirm the pass — never trust a subagent's report that it graded. Log every
   call to experiments/breadth/run/ledger.jsonl. A cell is 'settled' only at 3/3.

3. RESIDUAL: the tasks the floor did NOT clear 3/3. If the residual is EMPTY, STOP:
   print the map, do NOT run Fable at all, and tell me the floor won. Do not spend a
   frontier token to confirm a floor.

4. ESCALATE (only if residual is non-empty): walk ONLY the residual up rungs.ladder()
   from fable@low, K=3 per rung, sequentially from a constant cwd (exploit the 1h
   cache). 3/3 clears → record that rung; 0/3 wall → step up; 1-2/3 → run more trials,
   never step up on noise. Log real billed USD (total_cost_usd) per call.

5. ADAPT under adapt.py: improve HOW you solve/run freely; NEVER change a grader or
   what counts as passing — propose those to run/harness_log.jsonl (it forces
   applied=False). At ~80% of my Fable quota, STOP and print limit.decision_packet;
   do NOT escalate access — that's my call.

6. SEAL: append the verdicts as a new sediment layer to run/known_corner.jsonl and
   refresh run/KNOWN_CORNER.md. DIFF against the newest layer first — only re-probe
   non-'settled' cells; never re-derive settled sediment.

Report: settled vs liquid vs open, real Fable USD spent, and the decision packet.
If you find the floor clears everything even hidden-graded, that's the finding —
to find the real wall, we author novel-reasoning / counterexample tasks (task06
shape), not richer specs. Say so instead of burning Fable to look busy.
```

---

Optional (bigger orchestration): `experiments/breadth/build_known_corner.workflow.js`
is the same flow as a Workflow (parallel floor → escalate-only-walls → seal). Grow
its `CORNER` list and invoke it with the Workflow tool for a fully orchestrated fan-out.
