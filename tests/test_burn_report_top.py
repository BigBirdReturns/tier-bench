#!/usr/bin/env python3
"""Acceptance test for the --top N flag of scripts/burn_report.py.

--top N limits the per-session rows to the N most expensive sessions;
the summary block is unchanged (still computed over ALL sessions).
Stdlib only, deterministic, exit 0 iff PASS.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/burn_report.py"


def run(state_dir: Path, *extra: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--state-dir", str(state_dir), *extra],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return proc.stdout


def main() -> int:
    assert SCRIPT.exists(), "scripts/burn_report.py does not exist"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        fixtures = {
            "aaaaaaaa-1111": {"cost_usd": 3.0, "tier": None},
            "bbbbbbbb-2222": {"cost_usd": 10.0, "tier": "NOTICE"},
            "cccccccc-3333": {"cost_usd": 1.0, "tier": None},
            "dddddddd-4444": {"cost_usd": 4.0, "tier": None},
            "eeeeeeee-5555": {"cost_usd": 2.0, "tier": None},
        }
        for sid, payload in fixtures.items():
            (d / f"{sid}.json").write_text(json.dumps(payload), encoding="utf-8")

        summary = [
            "sessions: 5",
            "total: $20.00",
            "median: $3.00",
            "p90: $10.00",
        ]

        # --top 2: only the 2 most expensive rows, summary over all 5
        lines = [ln.rstrip("\r") for ln in run(d, "--top", "2").splitlines()]
        assert lines[:2] == [
            "bbbbbbbb  $10.00  NOTICE",
            "dddddddd  $4.00  -",
        ], f"--top 2 rows mismatch: {lines[:2]}"
        assert lines[2] == "", f"expected blank line, got {lines[2]!r}"
        assert lines[3:7] == summary, f"--top 2 summary mismatch: {lines[3:7]}"
        assert len(lines) == 7, f"unexpected extra output: {lines}"

        # --top larger than session count: identical to no flag
        assert run(d, "--top", "99") == run(d), "--top 99 should equal unlimited"

        # --top 0: no rows, summary intact
        lines0 = [ln.rstrip("\r") for ln in run(d, "--top", "0").splitlines()]
        assert lines0 == [""] + summary, f"--top 0 output mismatch: {lines0}"

        # negative N rejected
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--state-dir", str(d), "--top", "-1"],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode != 0, "--top -1 should be rejected"

    print("PASS burn_report_top")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL burn_report_top: {e}")
        raise SystemExit(1)
