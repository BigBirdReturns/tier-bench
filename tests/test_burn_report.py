#!/usr/bin/env python3
"""Driver-authored acceptance referee for crate burn_report_v1.

The hand implementing scripts/burn_report.py may RUN this file, never edit it
(adapt.py grader-ownership law). Stdlib only, deterministic, exit 0 iff PASS.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/burn_report.py"


def run(state_dir: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--state-dir", str(state_dir)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return proc.stdout


def main() -> int:
    assert SCRIPT.exists(), "scripts/burn_report.py does not exist"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        fixtures = {
            "aaaaaaaa-1111": {"offset": 10, "cost_usd": 3.0, "tier": None},
            "bbbbbbbb-2222": {"offset": 10, "cost_usd": 10.0, "tier": "NOTICE"},
            "cccccccc-3333": {"offset": 10, "cost_usd": 1.0, "tier": None},
            "dddddddd-4444": {"offset": 10, "cost_usd": 4.0, "tier": None},
            "eeeeeeee-5555": {"offset": 10, "cost_usd": 2.0, "tier": None},
        }
        for sid, payload in fixtures.items():
            (d / f"{sid}.json").write_text(json.dumps(payload), encoding="utf-8")
        # must be ignored:
        (d / "zzzzzzzz-9999.ack").write_text("400\n", encoding="utf-8")
        (d / "broken.json").write_text("{not json", encoding="utf-8")

        out = run(d)
        lines = [ln.rstrip("\r") for ln in out.splitlines()]

        expect_rows = [
            "bbbbbbbb  $10.00  NOTICE",
            "dddddddd  $4.00  -",
            "aaaaaaaa  $3.00  -",
            "eeeeeeee  $2.00  -",
            "cccccccc  $1.00  -",
        ]
        assert lines[:5] == expect_rows, f"rows mismatch:\n{lines[:5]}\nvs\n{expect_rows}"
        assert lines[5] == "", f"expected blank line, got {lines[5]!r}"
        assert lines[6:10] == [
            "sessions: 5",
            "total: $20.00",
            "median: $3.00",   # nearest-rank p50 of [1,2,3,4,10]
            "p90: $10.00",     # ceil(0.9*5)=5th ascending
        ], f"summary mismatch: {lines[6:10]}"

        # empty dir
        empty = d / "empty"
        empty.mkdir()
        out2 = run(empty)
        assert out2.strip() == "no sessions", f"empty-dir output: {out2!r}"

    print("PASS burn_report")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL burn_report: {e}")
        raise SystemExit(1)
