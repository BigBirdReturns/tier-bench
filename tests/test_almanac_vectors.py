#!/usr/bin/env python3
"""Tests for the almanac hidden-knot corpus (ARC-B). Stdlib only; runs under
pytest or standalone. Proves: frozen vectors match a fresh reference
derivation, graders are deterministic, the key material behaves (reference
passes, naive fails), the tasks are breadth-valid, and the knot vectors do not
leak into any solver-visible file."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiments" / "breadth"))
sys.path.insert(0, str(REPO / "experiments" / "almanac"))

import breadth_tasks  # noqa: E402
import generate_vectors as gv  # noqa: E402

TASKS = ["almanac_rule_boundary_001", "almanac_record_binding_001",
         "almanac_exception_class_001"]


def _run_grader(task: str, candidate: Path) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as w:
        for f in (REPO / "fixtures" / task).iterdir():
            shutil.copy(f, w)
        shutil.copy(candidate, Path(w) / "input.py")
        r = subprocess.run([sys.executable, "hidden_tests.py"], cwd=w,
                           capture_output=True, text=True, timeout=60)
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
            if f.name == "hidden_tests.py":
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
