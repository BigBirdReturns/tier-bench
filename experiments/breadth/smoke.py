#!/usr/bin/env python3
"""
Prove the keyless spine on ONE real task before spending any quota: grade -> ledger
-> breadth map. No model call, no API key, $0.

What this DOES prove: a real task manifest grades deterministically (its own test
runner), the outcome logs to the ledger, and escalate.py turns trials into a map.
What it does NOT do: solve the task. Solving is the model's job in the real run —
the session (or an Agent-tool subagent) writes the target file, then this same
grade->log->map spine scores it. Here we grade the UNSOLVED target, so the expected
outcome is `fail`; when a model actually solves it, the outcome flips to `pass` and
the map updates. Either way the wiring is what's under test.

    python experiments/breadth/smoke.py                       # default task
    python experiments/breadth/smoke.py tasks/t2_fix_failing_test_001.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.breadth.ledger import log_call, load          # noqa: E402
from experiments.breadth.escalate import breadth_map           # noqa: E402
from experiments.breadth.rungs import ladder, rung_costs       # noqa: E402


def grade_unsolved(manifest_path: Path) -> tuple[str, str]:
    """Run the task's own runner on the current (unsolved) target. Returns (task_id, outcome)."""
    d = json.loads(manifest_path.read_text())
    fx = (REPO / d["fixture_dir"]).resolve()
    if not fx.exists():
        raise SystemExit(f"fixture missing: {fx}")
    r = subprocess.run(d.get("run_command", ["python", "input.py"]),
                       cwd=fx, capture_output=True, text=True)
    return d["task_id"], ("pass" if r.returncode == 0 else "fail")


def main() -> int:
    manifest = Path(sys.argv[1]) if len(sys.argv) > 1 else (REPO / "tasks" / "t2_fix_failing_test_001.json")
    if not manifest.is_absolute():
        manifest = (REPO / manifest)
    task_id, outcome = grade_unsolved(manifest)

    led = REPO / "experiments" / "breadth" / "run" / "_smoke_ledger.jsonl"
    if led.exists():
        led.unlink()
    log_call(led, ts="1970-01-01T00:00:00Z", account="smoke", model="claude-haiku-4-5",
             tier="claude-haiku-4-5@harness", task_id=task_id, phase="harness",
             effort="n/a", input_tokens=0, output_tokens=0, cost_usd=0.0,
             outcome=outcome, trial=0, note="keyless spine smoke — unsolved target")

    rows = load(led)
    trials = [{"task_id": r["task_id"], "tier": r["tier"], "outcome": r["outcome"]} for r in rows]
    bmap = breadth_map(trials, ladder(), rung_costs())

    print(f"[smoke] task={task_id}  graded (unsolved) -> {outcome}  (fail is expected until a model solves it)")
    print(f"[smoke] ledger rows: {len(rows)}   map tasks: {list(bmap['tasks'])}")
    ok = len(rows) == 1 and task_id in bmap["tasks"]
    print(f"[smoke] SPINE {'OK — grade->ledger->map wired keyless' if ok else 'BROKEN'}")
    print("[smoke] the only piece not exercised here is the model solving the task; that is the "
          "session's job in Phase 1/2 of the RUNBOOK.")
    led.unlink(missing_ok=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
