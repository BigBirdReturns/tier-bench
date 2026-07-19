#!/usr/bin/env python3
"""Frozen referee for X3: dispatch.py --dry-run. Exit 0 = PASS.

Uses sentinel-file commands: if dispatch actually runs them, files appear.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
DISPATCH = ROOT / "scripts" / "dispatch.py"


def run(extra):
    return subprocess.run(
        [sys.executable, str(DISPATCH), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=180,
    )


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        sent_hand = tdp / "hand_ran.txt"
        sent_ref = tdp / "ref_ran.txt"
        receipt = tdp / "receipt_dry.md"
        hand_cmd = (
            'python -c "import pathlib; '
            f"pathlib.Path(r'{sent_hand}').write_text('x')\""
        )
        ref_cmd = (
            'python -c "import pathlib; '
            f"pathlib.Path(r'{sent_ref}').write_text('x')\""
        )

        # 1. --dry-run: exit 0, prints both commands, runs nothing, writes nothing
        r = run(["--arm-dir", str(ROOT), "--hand-cmd", hand_cmd,
                 "--referee", ref_cmd, "--receipt", str(receipt), "--dry-run"])
        if r.returncode != 0:
            fail(f"--dry-run exit {r.returncode}: {(r.stderr or '').strip()[:200]}")
        out = r.stdout
        if "hand_ran.txt" not in out:
            fail("--dry-run did not print the resolved hand command")
        if "ref_ran.txt" not in out:
            fail("--dry-run did not print the resolved referee command")
        if sent_hand.exists():
            fail("--dry-run RAN the hand command")
        if sent_ref.exists():
            fail("--dry-run RAN the referee command")
        if receipt.exists():
            fail("--dry-run wrote a receipt")
        if list(tdp.glob("*.log")):
            fail("--dry-run wrote a log file")

        # 2. Without --dry-run: behavior unchanged (runs, receipts, exit 0 on pass)
        receipt2 = tdp / "receipt_real.md"
        r = run(["--arm-dir", str(ROOT), "--hand-cmd", "echo baseline_hand",
                 "--referee", 'python -c "print(\'REF_OK\')"',
                 "--receipt", str(receipt2)])
        if r.returncode != 0:
            fail(f"normal dispatch broke: exit {r.returncode}: {(r.stderr or '').strip()[:200]}")
        if not receipt2.exists():
            fail("normal dispatch no longer writes a receipt")
        rows = [l for l in receipt2.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(rows) != 1:
            fail(f"normal dispatch wrote {len(rows)} receipt rows, want 1")
        try:
            row = json.loads(rows[0])
        except Exception as e:
            fail(f"receipt row not JSON: {e}")
        if row.get("pass") is not True:
            fail(f"normal dispatch receipt pass={row.get('pass')}, want true")

    print("PASS: X3 referee ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
