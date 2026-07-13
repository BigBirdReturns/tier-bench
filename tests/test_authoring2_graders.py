#!/usr/bin/env python3
"""Regression tests for the authoring-batch-2 hidden graders.

Proves (per PR #84 cross-engine review findings 1–2):
  * the graders ENFORCE declared return types — a wrong container
    (list[list] where list[tuple] is declared, list where tuple is declared,
    int where bool is declared) fails even with correct values;
  * correct-type reference implementations still score full marks;
  * build_vectors.py --check fails on a tampered verification receipt.

Runs under pytest or standalone, stdlib only.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

REF = {
    # correct values, declared container types
    "t3_billing_anchor_001": '''
def _leap(y): return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
def _dim(y, m):
    return [31, 29 if _leap(y) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
def billing_dates(y, m, d, n):
    out = []
    for i in range(1, n + 1):
        mm = m - 1 + i
        yy, mm2 = y + mm // 12, mm % 12 + 1
        out.append((yy, mm2, min(d, _dim(yy, mm2))))
    return out
''',
    "t3_window_limit_001": '''
def allow(events, w, n, t):
    return sum(1 for s in events if t - w < s <= t) < n
''',
    "t3_due_date_shift_001": '''
import datetime as _dt
def _biz(y, m, d, hol):
    return _dt.date(y, m, d).weekday() < 5 and (y, m, d) not in hol
def due_date(y, m, day, holidays):
    if _biz(y, m, day, holidays):
        return (y, m, day)
    cur = _dt.date(y, m, day)
    while True:
        cur += _dt.timedelta(days=1)
        if _biz(cur.year, cur.month, cur.day, holidays):
            break
    if cur.month == m and cur.year == y:
        return (cur.year, cur.month, cur.day)
    cur = _dt.date(y, m, day)
    while True:
        cur -= _dt.timedelta(days=1)
        if _biz(cur.year, cur.month, cur.day, holidays):
            return (cur.year, cur.month, cur.day)
''',
}

# identical values, WRONG container types — must fail every vector
WRONG_TYPE = {
    "t3_billing_anchor_001": REF["t3_billing_anchor_001"].replace(
        "out.append((yy, mm2, min(d, _dim(yy, mm2))))",
        "out.append([yy, mm2, min(d, _dim(yy, mm2))])"),   # list[list[int]]
    "t3_window_limit_001": REF["t3_window_limit_001"].replace(
        "return sum", "return 1 if sum(1 for s in events if t - w < s <= t) < n else 0"
    ).replace("(1 for s in events if t - w < s <= t) < n\n", "\n"),  # int, not bool
    "t3_due_date_shift_001": REF["t3_due_date_shift_001"]
        .replace("return (y, m, day)", "return [y, m, day]")
        .replace("return (cur.year, cur.month, cur.day)", "return [cur.year, cur.month, cur.day]"),
}


def _splice_and_grade(task: str, impl: str) -> tuple[int, str]:
    fixture = (REPO / "fixtures" / task / "input.py").read_text()
    m = re.search(r"def \w+\([^)]*\)[^\n]*:\n    raise NotImplementedError\n", fixture)
    assert m, f"stub not found in {task}"
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "input.py").write_text(fixture.replace(m.group(0), impl + "\n"))
        shutil.copy(REPO / "fixtures" / task / "hidden_tests.py", d / "hidden_tests.py")
        p = subprocess.run([sys.executable, "hidden_tests.py"], cwd=td,
                           capture_output=True, text=True)
        return p.returncode, p.stdout


def test_reference_types_score_full():
    for task in REF:
        rc, out = _splice_and_grade(task, REF[task])
        assert rc == 0, f"{task}: correct-type reference failed: {out[:200]}"
        assert re.search(r"SCORE (\d+)/\1", out), f"{task}: not a full score: {out[:80]}"


def test_wrong_container_types_fail():
    for task in WRONG_TYPE:
        rc, out = _splice_and_grade(task, WRONG_TYPE[task])
        assert rc != 0, f"{task}: wrong-container implementation scored PASS: {out[:200]}"
        m = re.match(r"SCORE (\d+)/(\d+)", out)
        assert m and int(m.group(1)) < int(m.group(2)), f"{task}: unexpected score: {out[:80]}"
        # every non-vacuous vector must fail on the container type; only vectors
        # whose expected value is EMPTY (indistinguishable when empty) may pass
        vectors = eval(re.search(r"VECTORS = (\[.*?\n\])", (REPO / "fixtures" / task / "hidden_tests.py").read_text(), re.S).group(1))  # noqa: S307
        vacuous = sum(1 for _, want in vectors if want == [])
        assert int(m.group(1)) <= vacuous, (
            f"{task}: wrong container passed {m.group(1)} vectors but only "
            f"{vacuous} are vacuously (empty-value) conformant")


def test_check_mode_detects_tampered_receipt():
    rpath = REPO / "experiments/breadth/authoring2/verification_receipt.json"
    original = rpath.read_text()
    try:
        tampered = json.loads(original)
        next(iter(tampered.values()))["vectors"] = 999
        rpath.write_text(json.dumps(tampered, indent=2) + "\n")
        p = subprocess.run(
            [sys.executable, "experiments/breadth/authoring2/build_vectors.py", "--check"],
            cwd=str(REPO), capture_output=True, text=True)
        assert p.returncode != 0, "--check passed on a tampered verification receipt"
        assert "DRIFT" in p.stdout
    finally:
        rpath.write_text(original)


def test_check_mode_green_on_clean_tree():
    p = subprocess.run(
        [sys.executable, "experiments/breadth/authoring2/build_vectors.py", "--check"],
        cwd=str(REPO), capture_output=True, text=True)
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
