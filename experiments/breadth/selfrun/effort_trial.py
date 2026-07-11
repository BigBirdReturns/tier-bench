#!/usr/bin/env python3
"""Run one task's K trials at a controlled effort rung via a nested Claude Code
CLI, grade with the task's own (and hidden) validators, and log EXACT telemetry:
tokens including cache read/write splits, and REAL billed USD (total_cost_usd).

Requires the `claude` CLI on PATH with working auth (subscription or key).
Run trials SEQUENTIALLY from a constant cwd: the 1h prompt cache is then written
once and read thereafter (~half the cost of parallel cold calls).

    python experiments/breadth/selfrun/effort_trial.py TASK_ID --scratch DIR \
        --effort low [--model claude-fable-5] [--trials 0,1,2] [--ledger PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from experiments.breadth.ledger import log_call  # noqa: E402
from harness.hidden_grading import run_hidden_grader  # noqa: E402
from harness.task_schema import Task  # noqa: E402
from harness.validators import capture_behavior, validate_all  # noqa: E402

EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--effort", required=True, choices=EFFORTS)
    ap.add_argument("--model", default="claude-fable-5")
    ap.add_argument("--trials", default="0,1,2")
    ap.add_argument("--timeout", type=int, default=480)
    ap.add_argument("--ledger", default=str(REPO / "experiments/breadth/run/ledger.jsonl"))
    a = ap.parse_args()

    scratch = Path(a.scratch)
    index = json.loads((scratch / "index.json").read_text())
    info = index[a.task_id]
    task = Task.from_json(Path(info["manifest"]))
    runcmd = " ".join(info["run_command"])
    crit = ("stdout/stderr/exit code must be BYTE-IDENTICAL to the baseline in prompt.txt"
            if task.validate.get("functional_equivalence") else "it must exit 0 and print OK")

    for k in [int(x) for x in a.trials.split(",")]:
        tdir = Path(info["trials"][str(k)])
        repo = tdir / "repo"
        prompt = f"""Solve a coding task in the git working copy at {repo}

1. Read {tdir}/prompt.txt — the complete task, current file content, and baseline behavior.
2. Where the task says "Return ONLY the full updated content for {task.target_relpath}", that means: WRITE the full updated content to {repo}/{task.target_relpath} (overwrite it). Do NOT paste file content in your reply.
3. Modify ONLY {task.target_relpath} in that repo. Do not touch any other file. Do not run any git commands.
4. Verify: run `{runcmd}` in {repo} — {crit}
5. Reply with exactly one line: DONE + a one-sentence summary."""

        p = subprocess.run(
            ["claude", "-p", prompt, "--model", a.model, "--effort", a.effort,
             "--output-format", "json", "--add-dir", str(scratch),
             "--allowedTools", "Read", "Write", "Edit", "Bash", "Glob", "Grep",
             "--permission-mode", "acceptEdits"],
            cwd=str(REPO), capture_output=True, text=True, timeout=a.timeout,
        )
        try:
            r = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            r = {"is_error": True, "result": f"CLI parse failure rc={p.returncode}"}
        u = r.get("usage", {})

        b = json.loads((tdir / "baseline.json").read_text())
        after = capture_behavior(repo, task.run_command)
        v = validate_all(
            cwd=repo, target_relpath=task.target_relpath, run_command=task.run_command,
            max_lines_changed=task.max_lines_changed, allowed_files=task.allowed_files,
            require_functional_equivalence=bool(task.validate.get("functional_equivalence")),
            require_ruff_imports=bool(task.validate.get("ruff_imports")),
            require_compile=bool(task.validate.get("compile")),
            require_tests=bool(task.validate.get("tests")),
            before=(b["rc"], b["stdout"], b["stderr"]), after=after,
        )
        hidden_ok = True
        hidden_timed_out = False
        if task.hidden_run_command:
            h = run_hidden_grader(task, repo, fixture_dir=REPO / task.fixture_dir)
            hidden_ok = (h.returncode == 0)
            hidden_timed_out = h.timed_out

        outcome = "error" if r.get("is_error") else ("pass" if (v.pass_all and hidden_ok) else "fail")
        row = log_call(
            a.ledger,
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            account="claude-code-session", model=a.model, tier=f"{a.model}@{a.effort}",
            task_id=a.task_id, phase="baseline", outcome=outcome, effort=a.effort,
            input_tokens=int(u.get("input_tokens", 0)),
            output_tokens=int(u.get("output_tokens", 0)),
            cache_read_tokens=int(u.get("cache_read_input_tokens", 0)),
            cache_write_tokens=int(u.get("cache_creation_input_tokens", 0)),
            cost_usd=float(r.get("total_cost_usd", 0.0)),
            latency_ms=float(r.get("duration_ms", 0.0)), trial=k,
            note="nested claude CLI solve; cost_usd is REAL billed cost, tokens exact incl. cache splits",
            validators={"diff_lines": v.diff_lines, "tests_ok": v.tests_ok,
                        "hidden_ok": hidden_ok, "hidden_timed_out": hidden_timed_out,
                        "after_rc": after[0]},
            cli={"num_turns": r.get("num_turns"), "stop_reason": r.get("stop_reason")},
        )
        print(json.dumps({"task_id": a.task_id, "trial": k, "outcome": outcome,
                          "cost_usd": row.cost_usd, "cache_r": row.cache_read_tokens,
                          "hidden_ok": hidden_ok, "ms": row.latency_ms}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
