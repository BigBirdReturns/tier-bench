#!/usr/bin/env python3
"""Grade one solved trial deterministically and log it to the run ledger.

The solver is OFF the scoring path: this reads what the solver wrote and applies
harness.validators.validate_all with the PRE-EDIT baseline captured at prep time,
then — if the manifest declares hidden grading — injects the hidden files from
the committed fixture and requires hidden_run_command to exit 0.

    python experiments/breadth/selfrun/grade.py TASK_ID TRIAL --scratch DIR \
        [--model claude-haiku-4-5] [--tier claude-haiku-4-5@harness] [--effort ""] \
        [--in-tokens N --out-tokens N --cost-usd X --latency-ms MS] [--note S] [--ledger PATH]

Token/cost fields: pass exact numbers when the surface reports them; estimates
must say so in --note (a blank is a logged blank, never a silent gap).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from experiments.breadth.ledger import log_call  # noqa: E402
from harness.task_schema import Task  # noqa: E402
from harness.validators import capture_behavior, validate_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("trial", type=int)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--tier", default="claude-haiku-4-5@harness")
    ap.add_argument("--effort", default="")
    ap.add_argument("--phase", default="baseline")
    ap.add_argument("--account", default="claude-code-session")
    ap.add_argument("--in-tokens", type=int, default=0)
    ap.add_argument("--out-tokens", type=int, default=0)
    ap.add_argument("--cache-read-tokens", type=int, default=0)
    ap.add_argument("--cache-write-tokens", type=int, default=0)
    ap.add_argument("--cost-usd", type=float, default=0.0)
    ap.add_argument("--latency-ms", type=float, default=0.0)
    ap.add_argument("--note", default="")
    ap.add_argument("--ledger", default=str(REPO / "experiments/breadth/run/ledger.jsonl"))
    a = ap.parse_args()

    index = json.loads((Path(a.scratch) / "index.json").read_text())
    info = index[a.task_id]
    task = Task.from_json(Path(info["manifest"]))
    tdir = Path(info["trials"][str(a.trial)])
    repo = tdir / "repo"
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
    if task.hidden_run_command:
        for hf in (task.hidden_files or []):
            shutil.copy2(REPO / task.fixture_dir / hf, repo / hf)
        h = subprocess.run(task.hidden_run_command, cwd=str(repo), capture_output=True, text=True)
        hidden_ok = (h.returncode == 0)
        for hf in (task.hidden_files or []):
            (repo / hf).unlink(missing_ok=True)

    outcome = "pass" if (v.pass_all and hidden_ok) else "fail"
    detail = {"compile_ok": v.compile_ok, "ruff_imports_ok": v.ruff_imports_ok,
              "functional_equivalence": v.functional_equivalence, "diff_lines": v.diff_lines,
              "changed_files": v.changed_files, "allowed_files_ok": v.allowed_files_ok,
              "max_lines_ok": v.max_lines_ok, "tests_ok": v.tests_ok,
              "hidden_ok": hidden_ok, "after_rc": after[0]}
    log_call(
        a.ledger,
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        account=a.account, model=a.model, tier=a.tier, task_id=a.task_id,
        phase=a.phase, outcome=outcome, effort=a.effort,
        input_tokens=a.in_tokens, output_tokens=a.out_tokens,
        cache_read_tokens=a.cache_read_tokens, cache_write_tokens=a.cache_write_tokens,
        cost_usd=a.cost_usd, latency_ms=a.latency_ms, trial=a.trial,
        note=a.note, validators=detail,
    )
    print(json.dumps({"task_id": a.task_id, "trial": a.trial, "outcome": outcome, **detail}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
