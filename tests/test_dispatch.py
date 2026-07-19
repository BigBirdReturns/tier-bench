#!/usr/bin/env python3
"""Driver-authored referee for crate dispatch_v1. Frozen; hands run, never edit."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/dispatch.py"

CHECK = (
    "import sys, pathlib\n"
    "ok = pathlib.Path('flag.txt').exists()\n"
    "print('PASS check' if ok else 'FAIL check')\n"
    "sys.exit(0 if ok else 1)\n"
)


def dispatch(arm, hand_cmd, receipt):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--arm-dir", str(arm), "--hand-cmd", hand_cmd,
         "--referee", f'"{sys.executable}" tests/check.py', "--receipt", str(receipt)],
        capture_output=True, text=True, timeout=120,
    )


def main() -> int:
    assert SCRIPT.exists(), "scripts/dispatch.py does not exist"
    with tempfile.TemporaryDirectory() as td:
        arm = Path(td) / "arm"
        (arm / "tests").mkdir(parents=True)
        (arm / "tests" / "check.py").write_text(CHECK, encoding="utf-8")
        receipt = Path(td) / "out" / "receipt.jsonl"

        good = f'"{sys.executable}" -c "open(\'flag.txt\',\'w\').write(\'x\')"'
        p1 = dispatch(arm, good, receipt)
        assert p1.returncode == 0, f"pass-case exit {p1.returncode}: {p1.stderr}"

        (arm / "flag.txt").unlink()
        bad = f'"{sys.executable}" -c "pass"'
        p2 = dispatch(arm, bad, receipt)
        assert p2.returncode == 2, f"fail-case exit {p2.returncode}: {p2.stderr}"

        rows = [json.loads(l) for l in receipt.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(rows) == 2, f"expected 2 appended rows, got {len(rows)}"
        assert rows[0]["pass"] is True and rows[0]["referee_exit"] == 0
        assert rows[0]["referee_last_line"] == "PASS check"
        assert rows[1]["pass"] is False and rows[1]["referee_exit"] != 0
        for r in rows:
            assert Path(r["log"]).exists(), f"missing log {r['log']}"
            assert r["hand_cmd"], "hand_cmd missing"
        assert rows[0]["log"] != rows[1]["log"], "logs must not overwrite"

    print("PASS dispatch")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL dispatch: {e}")
        raise SystemExit(1)
