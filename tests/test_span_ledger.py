#!/usr/bin/env python3
"""Driver-authored acceptance referee for crate span_ledger_v1. Frozen: the
implementing hand may run this file, never edit it."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/span_ledger.py"


def run(input_path) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(input_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return "\n".join(ln.rstrip("\r") for ln in proc.stdout.splitlines())


def case(lines, expect):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8") as f:
        for ln in lines:
            f.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")
        p = Path(f.name)
    try:
        got = run(p)
        assert got == expect, f"for {lines!r}:\n got: {got!r}\nwant: {expect!r}"
    finally:
        p.unlink(missing_ok=True)


def main() -> int:
    assert SCRIPT.exists(), "scripts/span_ledger.py does not exist"

    # unsorted + touching chain merges to one
    case([{"start": 5, "end": 10}, {"start": 1, "end": 3}, {"start": 3, "end": 5}],
         "merged: 1\ncovered: 9")
    # disjoint + overlap
    case([{"start": 0, "end": 2}, {"start": 10, "end": 12}, {"start": 11, "end": 15}],
         "merged: 2\ncovered: 7")
    # duplicates collapse; garbage and inverted/boolean spans ignored
    case([{"start": 1, "end": 3}, {"start": 1, "end": 3}, {"start": 2, "end": 4},
          "not json", {"start": 9, "end": 9}, {"start": 8, "end": 4},
          {"start": True, "end": 7}, {"start": 0.5, "end": 2}],
         "merged: 1\ncovered: 3")
    # nothing valid
    case(["nope", {"start": 4, "end": 4}], "no spans")
    # missing file
    got = run(REPO / "does_not_exist.jsonl")
    assert got == "no spans", f"missing file: {got!r}"

    print("PASS span_ledger")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL span_ledger: {e}")
        raise SystemExit(1)
