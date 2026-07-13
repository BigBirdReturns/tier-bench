#!/usr/bin/env python3
"""Regression tests for the authoring-batch-3 hidden graders.

Proves, per the batch-2 post-review standard (applied here from the start):
  * baseline fixtures fail their hidden graders (no free passes);
  * the reference implementations pass the visible checks AND score full on
    the hidden vectors;
  * each paired naive passes the VISIBLE checks but fails the hidden grader —
    the visible/hidden daylight is the measurement;
  * wrong return-container types fail even with correct values;
  * build_vectors.py --check fails on a tampered verification receipt.

Runs under pytest or standalone, stdlib only.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BV = REPO / "experiments/breadth/authoring3/build_vectors.py"

spec = importlib.util.spec_from_file_location("bv3", BV)
bv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv)


def _src(fn, rename_to):
    return inspect.getsource(fn).replace(fn.__name__, rename_to, 1)


REF = {
    "t3_null_filter_001": (
        'TRUE, FALSE, UNKNOWN = "T", "F", "U"\n'
        + inspect.getsource(bv._cmp) + "\n" + inspect.getsource(bv._kleene) + "\n"
        + _src(bv.ref_select, "select_ids")),
    "t3_accrual_crossover_001": _src(bv.ref_crossover, "crossover_day"),
}
NAIVE = {
    # every declared naive gets the visible-OK / hidden-FAIL proof
    "t3_null_filter_001": {
        "none_is_false": (
            inspect.getsource(bv._cmp) + "\n" + inspect.getsource(bv._boolish) + "\n"
            + _src(bv.naive_none_is_false, "select_ids")),
        "skip_none": (
            inspect.getsource(bv._cmp) + "\n" + inspect.getsource(bv._boolish) + "\n"
            + inspect.getsource(bv._touches_none) + "\n"
            + _src(bv.naive_skip_none, "select_ids")),
    },
    "t3_accrual_crossover_001": {
        "float_formula": _src(bv.naive_float_formula, "crossover_day"),
    },
}
WRONG_TYPE = {
    # correct values, wrong containers
    "t3_null_filter_001": REF["t3_null_filter_001"].replace(
        'return [r["id"] for r in records if _kleene(r, condition) == TRUE]',
        'return tuple(r["id"] for r in records if _kleene(r, condition) == TRUE)'),
    "t3_accrual_crossover_001": REF["t3_accrual_crossover_001"]
        .replace("return 0", "return float(0)")
        .replace("return d", "return float(d)"),
}


def _splice_and_run(task: str, impl: str):
    fixture = (REPO / "fixtures" / task / "input.py").read_text()
    m = re.search(r"def \w+\([^)]*\)[^\n]*:\n    raise NotImplementedError\n", fixture)
    assert m, f"stub not found in {task}"
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "input.py").write_text(fixture.replace(m.group(0), impl + "\n"))
        shutil.copy(REPO / "fixtures" / task / "hidden_tests.py", d / "hidden_tests.py")
        vis = subprocess.run([sys.executable, "input.py"], cwd=td, capture_output=True, text=True)
        hid = subprocess.run([sys.executable, "hidden_tests.py"], cwd=td, capture_output=True, text=True)
        return vis, hid


def test_baseline_fails_hidden():
    for task in REF:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            shutil.copy(REPO / "fixtures" / task / "input.py", d / "input.py")
            shutil.copy(REPO / "fixtures" / task / "hidden_tests.py", d / "hidden_tests.py")
            p = subprocess.run([sys.executable, "hidden_tests.py"], cwd=td,
                               capture_output=True, text=True)
            assert p.returncode != 0, f"{task}: baseline passed its hidden grader"


def test_reference_passes_visible_and_hidden():
    for task in REF:
        vis, hid = _splice_and_run(task, REF[task])
        assert vis.returncode == 0 and vis.stdout.strip().endswith("OK"), \
            f"{task}: reference failed visible checks: {vis.stdout[-200:]}{vis.stderr[-200:]}"
        assert hid.returncode == 0 and re.search(r"SCORE (\d+)/\1", hid.stdout), \
            f"{task}: reference not full hidden score: {hid.stdout[:100]}"


def test_every_declared_naive_passes_visible_fails_hidden():
    for task, naives in NAIVE.items():
        for name, impl in naives.items():
            vis, hid = _splice_and_run(task, impl)
            assert vis.returncode == 0 and vis.stdout.strip().endswith("OK"), \
                f"{task}/{name}: naive failed VISIBLE checks — knot not hidden enough: {vis.stdout[:150]}"
            assert hid.returncode != 0, \
                f"{task}/{name}: naive passed the hidden grader — no daylight"


def test_wrong_container_types_fail():
    for task in WRONG_TYPE:
        _, hid = _splice_and_run(task, WRONG_TYPE[task])
        assert hid.returncode != 0, f"{task}: wrong-container implementation passed"


def test_check_mode_detects_tampered_receipt():
    rpath = REPO / "experiments/breadth/authoring3/verification_receipt.json"
    original = rpath.read_text()
    try:
        tampered = json.loads(original)
        next(iter(tampered.values()))["vectors"] = 999
        rpath.write_text(json.dumps(tampered, indent=2) + "\n")
        p = subprocess.run([sys.executable, str(BV), "--check"], cwd=str(REPO),
                           capture_output=True, text=True)
        assert p.returncode != 0 and "DRIFT" in p.stdout
    finally:
        rpath.write_text(original)


def test_check_mode_green_on_clean_tree():
    p = subprocess.run([sys.executable, str(BV), "--check"], cwd=str(REPO),
                       capture_output=True, text=True)
    assert p.returncode == 0, f"--check failed on clean tree: {p.stdout[-300:]}"


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
