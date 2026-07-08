# Phase-1 loop — proven end-to-end on a real task, keyless

The smoke test proves the deterministic spine (grade → ledger → map). This proves
the piece the smoke leaves out: a real cheap model **solving** a task, and the grade
flipping `fail → pass` off live model output. Together they mean the full Phase-1
loop faults nowhere.

Task: `t2_fix_failing_test_001` — `safe_div` must return `0.0` when the divisor is
0, not raise. Solved in a scratch copy (the committed fixture is never mutated).

```
unsolved input.py         → grade (its own runner): FAIL — ZeroDivisionError, exit 1
haiku subagent solves it  → adds `if b == 0: return 0.0`     (~5.5s, ~17.8k tokens)
solved copy               → grade: "OK", exit 0 → PASS
ledger + breadth map      → t2_fix_failing_test_001 CLEARED at claude-haiku-4-5@harness ($0.03)
reconcile(ledger, bill)   → ✓
```

The solver was a real `haiku` instance via the Agent tool — no API key, exactly the
mechanism Phase 1 uses across the task set (× K=3). What this establishes:

- **The loop is real.** Model output → the target file → the task's own grader →
  a pass/fail the ledger records and the map reflects. No mock at any step.
- **It runs keyless.** The session model (or a subagent) is the solver; no
  `ANTHROPIC_API_KEY`, no `orchestrator.py` real-call path.
- **A mini-preview of the thesis.** This task cleared at the *cheap floor* on
  haiku's first try. If most of the set behaves this way, `residual.txt` comes back
  small or empty and Fable is never needed — the cheapest possible best baseline.

What this does NOT claim: **any capability result.** `t2` is a `tasks/*.json` task —
its grader is `python input.py`, the same file the solver edits, so the solver can
see the tests. That is fine for proving the *plumbing* (model output → file → grader
→ ledger → map) but it is **worthless as a capability measurement**: an agentic
solver reads the answer key and every such task "clears" for free. Real
breadth-mapping runs only on **hidden-grader** tasks where the deciding grader is
never shown to the solver — see `experiments/breadth/breadth_tasks.py` (today:
`task01`, `task02`, `task06`). Grow that set by authoring visible/hidden-daylight
tasks, never by pointing the run at gameable ones.
