#!/usr/bin/env python3
"""Tests for the almanac hidden-knot corpus (ARC-B). Stdlib only; runs under
pytest or standalone. Proves: frozen vectors match a fresh reference
derivation, graders are deterministic, the key material behaves (reference
passes, naive fails), the tasks are breadth-valid, and the knot vectors do not
leak into any solver-visible file."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "breadth"))
sys.path.insert(0, str(REPO / "experiments" / "almanac"))

import breadth_tasks  # noqa: E402
import generate_vectors as gv  # noqa: E402
from harness.hidden_grading import fixture_copy_ignore, run_hidden_grader  # noqa: E402
from harness.prompting import render_prompt  # noqa: E402
from harness.task_schema import Task  # noqa: E402
from scripts.validate_task import validate_task  # noqa: E402

TASKS = ["almanac_rule_boundary_001", "almanac_record_binding_001",
         "almanac_exception_class_001"]


def _run_grader(task: str, candidate: Path) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as w:
        for f in (REPO / "fixtures" / task).iterdir():
            if f.is_file():
                shutil.copy2(f, w)
        shutil.copy2(candidate, Path(w) / "input.py")
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        r = subprocess.run([sys.executable, "hidden_tests.py"], cwd=w,
                           capture_output=True, text=True, timeout=60, env=env)
        return r.returncode, r.stdout


def test_frozen_vectors_match_reference_derivation():
    fresh = gv.build()
    for task in TASKS:
        assert gv.frozen_vectors(task) == fresh[task], f"{task}: frozen vectors drifted"


def test_reference_passes_every_grader():
    for task in TASKS:
        rc, out = _run_grader(task, REPO / "experiments/almanac/key" / task / "REFERENCE.py")
        assert rc == 0, f"{task}: REFERENCE failed its own grader:\n{out}"


def test_naive_fails_every_grader():
    for task in TASKS:
        rc, out = _run_grader(task, REPO / "experiments/almanac/key" / task / "NAIVE.py")
        assert rc != 0, f"{task}: NAIVE school passed — the knot has no bite:\n{out}"


def test_graders_are_deterministic():
    for task in TASKS:
        runs = [_run_grader(task, REPO / "experiments/almanac/key" / task / "REFERENCE.py")
                for _ in range(2)]
        assert runs[0] == runs[1], f"{task}: grader output differs across runs"


def test_tasks_are_breadth_valid_and_not_gameable():
    listed = {t["task"] for t in breadth_tasks.breadth_valid_manifests()}
    for task in TASKS:
        assert task in listed, f"{task} not listed breadth-valid"
        assert not breadth_tasks.is_gameable(REPO / "tasks" / f"{task}.json")


def test_false_hidden_declarations_are_gameable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fixture = root / "fixture"
        fixture.mkdir()
        (fixture / "input.py").write_text("print('visible')\n", encoding="utf-8")
        (fixture / "hidden_tests.py").write_text("print('hidden')\n", encoding="utf-8")
        manifest = root / "task.json"
        base = {
            "fixture_dir": str(fixture),
            "target_relpath": "input.py",
            "allowed_files": ["input.py"],
            "hidden_files": ["hidden_tests.py"],
            "hidden_run_command": [sys.executable, "input.py"],
        }
        manifest.write_text(json.dumps(base), encoding="utf-8")
        assert breadth_tasks.is_gameable(manifest)
        base["hidden_run_command"] = [sys.executable, "hidden_tests.py"]
        manifest.write_text(json.dumps(base), encoding="utf-8")
        assert not breadth_tasks.is_gameable(manifest)
        (fixture / "hidden_tests.py").unlink()
        assert breadth_tasks.is_gameable(manifest)


def test_almanac_ids_pass_the_contribution_gate_without_renaming():
    for task in TASKS:
        assert validate_task(REPO / "tasks" / f"{task}.json") == []


def test_hidden_grader_name_and_bytes_are_absent_from_solver_prompt():
    for task_id in TASKS:
        task = Task.from_json(REPO / "tasks" / f"{task_id}.json")
        with tempfile.TemporaryDirectory() as td:
            solver_copy = Path(td) / "repo"
            shutil.copytree(REPO / task.fixture_dir, solver_copy, ignore=fixture_copy_ignore)
            hidden_source = REPO / task.fixture_dir / "hidden_tests.py"
            hidden_text = hidden_source.read_text(encoding="utf-8")
            (solver_copy / "hidden_tests.py").unlink()
            prompt = render_prompt(task.prompt_template, solver_copy, task.target_relpath)
            assert "hidden_tests.py" not in prompt
            assert hidden_text not in prompt


def test_fixture_copy_filter_is_pycache_idempotent():
    ignored = fixture_copy_ignore("unused", ["input.py", "__pycache__", "x.pyc", "x.pyo"])
    assert ignored == {"__pycache__", "x.pyc", "x.pyo"}


def test_hidden_grader_timeout_is_a_failed_result_not_a_hang():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "hidden_tests.py").write_text("pass\n", encoding="utf-8")
        repo = root / "repo"
        repo.mkdir()
        task = Task(
            task_id="timeout_probe", tier="T3", prompt_template="", fixture_dir=root,
            target_relpath="input.py", run_command=[sys.executable, "input.py"],
            validate={}, max_lines_changed=1, allowed_files=["input.py"],
            hidden_files=["hidden_tests.py"],
            hidden_run_command=[sys.executable, "-c", "import time; time.sleep(2)"],
        )
        result = run_hidden_grader(task, repo, timeout=0.05)
        assert result.timed_out
        assert result.returncode != 0
        assert not (repo / "hidden_tests.py").exists()


def test_knot_vectors_do_not_leak_into_visible_files():
    # Hidden-only vector inputs must not appear in any solver-visible fixture
    # file. Visible main() checks deliberately reuse a few ORDINARY vectors —
    # that daylight is the design — so only the knot vectors are asserted.
    knots = {
        "almanac_rule_boundary_001": ["2020, 1, 15", "2020, 2, 4", "2020, 2, 3", "2021, 1, 1"],
        "almanac_record_binding_001": ["1993, 8, 17", "23.98", "0.99"],
        "almanac_exception_class_001": ["1996, 7, 8", "1902, 3, 5", "1948, 2, 9"],
    }
    for task, needles in knots.items():
        for f in (REPO / "fixtures" / task).iterdir():
            if not f.is_file() or f.name == "hidden_tests.py":
                continue
            text = f.read_text(encoding="utf-8")
            for needle in needles:
                assert needle not in text, f"{task}/{f.name} leaks knot vector {needle!r}"


def test_manifests_load_in_the_real_harness_schema():
    sys.path.insert(0, str(REPO))
    from harness.task_schema import Task
    for task in TASKS:
        t = Task.from_json(REPO / "tasks" / f"{task}.json")
        assert t.hidden_files == ["hidden_tests.py"]
        assert t.hidden_run_command == ["python", "hidden_tests.py"]
        assert (REPO / t.fixture_dir / "hidden_tests.py").exists()


def _run_standalone() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
