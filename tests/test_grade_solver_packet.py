#!/usr/bin/env python3
"""Coordinator grading pipeline tests with the frozen almanac key material."""
from __future__ import annotations

import sys
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import export_solver_packet as exporter  # noqa: E402
import grade_solver_packet as grader  # noqa: E402

TASK = "almanac_exception_class_001"
MANIFEST = REPO / f"tasks/{TASK}.json"


@contextmanager
def _scratch():
    path = REPO / ".test-tmp" / f"grade-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _case(parent: Path, candidate_name: str):
    solver = parent / f"solver-{candidate_name}"
    receipt = parent / f"receipt-{candidate_name}.json"
    exporter.export_packet(MANIFEST, solver, receipt)
    raw = REPO / f"experiments/almanac/key/{TASK}/{candidate_name}.py"
    return grader.grade(receipt, solver, raw, parent / f"grade-{candidate_name}",
                        "coordinator-test")


def test_reference_passes_two_independent_grades():
    with _scratch() as parent:
        result = _case(parent, "REFERENCE")
        assert result["outcome"] == "pass"
        assert result["hidden_returncodes"] == [0, 0]
        assert result["hidden_grader_deterministic"] is True


def test_naive_school_fails_hidden_grader():
    with _scratch() as parent:
        result = _case(parent, "NAIVE")
        assert result["outcome"] == "fail"
        assert result["hidden_returncodes"] != [0, 0]


def test_packet_drift_is_rejected_before_grading():
    with _scratch() as parent:
        solver = parent / "solver"
        receipt = parent / "receipt.json"
        exporter.export_packet(MANIFEST, solver, receipt)
        (solver / "input.py").write_text("tampered\n", encoding="utf-8")
        try:
            grader.grade(receipt, solver,
                         REPO / f"experiments/almanac/key/{TASK}/REFERENCE.py",
                         parent / "grade", "coordinator-test")
        except ValueError as exc:
            assert "packet hash drifted" in str(exc)
        else:
            raise AssertionError("tampered packet should be rejected")


def _run_standalone() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test(); print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1; print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
