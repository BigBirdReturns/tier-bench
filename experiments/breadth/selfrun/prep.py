#!/usr/bin/env python3
"""Breadth self-run Phase-1 prep — one scratch working copy per (task, trial).

For every manifest in tasks/: copy the fixture (committed fixtures are never
mutated), REMOVE hidden grader files (an agentic solver iterates any grader it
can see — hidden files must not reach the copy or the rendered prompt),
git-init + baseline commit (diff bounds), capture PRE-EDIT behavior (so
functional_equivalence is real, not trivially true), and render the task's own
prompt to prompt.txt. Writes index.json mapping tasks -> trial dirs.

    python experiments/breadth/selfrun/prep.py /path/to/scratch [--k 3]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from harness.prompting import render_prompt  # noqa: E402
from harness.hidden_grading import fixture_copy_ignore  # noqa: E402
from harness.task_schema import Task  # noqa: E402
from harness.util_git import ensure_git_repo, git_commit_all  # noqa: E402
from harness.validators import capture_behavior  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scratch", help="scratch root for working copies (outside the repo)")
    ap.add_argument("--k", type=int, default=3, help="trials per task (default 3)")
    ap.add_argument("--tasks", default="", help="comma-separated task_ids (default: all)")
    a = ap.parse_args()
    scratch = Path(a.scratch)
    only = {t for t in a.tasks.split(",") if t}

    index: dict = {}
    for mp in sorted((REPO / "tasks").glob("*.json")):
        task = Task.from_json(mp)
        if only and task.task_id not in only:
            continue
        for k in range(a.k):
            tdir = scratch / task.task_id / f"trial{k}"
            repo = tdir / "repo"
            if tdir.exists():
                shutil.rmtree(tdir)
            repo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(REPO / task.fixture_dir, repo, ignore=fixture_copy_ignore)
            for hf in (task.hidden_files or []):
                (repo / hf).unlink(missing_ok=True)
            ensure_git_repo(repo)
            git_commit_all(repo, "baseline")
            rc, out, err = capture_behavior(repo, task.run_command)
            (tdir / "baseline.json").write_text(json.dumps({"rc": rc, "stdout": out, "stderr": err}))
            (tdir / "prompt.txt").write_text(render_prompt(
                task.prompt_template, repo, task.target_relpath,
                baseline={"rc": rc, "stdout": out, "stderr": err}))
            index.setdefault(task.task_id, {"manifest": str(mp), "target": task.target_relpath,
                                            "run_command": task.run_command, "tier": task.tier,
                                            "baseline_rc": rc, "trials": {}})
            index[task.task_id]["trials"][str(k)] = str(tdir)

    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "index.json").write_text(json.dumps(index, indent=2))
    for tid, info in index.items():
        print(f"{tid:32s} {info['tier']}  baseline_rc={info['baseline_rc']}  trials={len(info['trials'])}")
    print(f"index -> {scratch / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
