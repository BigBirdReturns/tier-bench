"""Referee for dispatch_fix_v1: pins UTF-8-safe capture in scripts/dispatch.py.

Frozen; hands run, never edit.

Pins (Windows cp1252 defect, CRATE_OPS backlog 2026-07-18): a hand whose
output contains UTF-8 bytes outside cp1252 (right double quote U+201D) must
be captured without raising; the log file must be readable as UTF-8 with the
hand's characters intact; the receipt row must carry the referee's full last
line (including U+201D) with pass=true / referee_exit=0.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "dispatch.py"

RDQ = "”"  # UTF-8 e2 80 9d; 0x9d has no cp1252 mapping, so locale decode raises
HAND_MARK = "hand-utf8-mark"
REFEREE_LINE = "PASS utf8 “full-line-intact”"

# Hand and referee emit raw UTF-8 bytes so the child's own stdout codec
# can't interfere; only dispatch.py's capture decoding is under test.
HAND_SRC = (
    "import sys\n"
    f"sys.stdout.buffer.write(({HAND_MARK!r} + ' ' + {RDQ!r} + '\\n').encode('utf-8'))\n"
)
CHECK_SRC = (
    "import sys\n"
    f"sys.stdout.buffer.write(({REFEREE_LINE!r} + '\\n').encode('utf-8'))\n"
    "sys.exit(0)\n"
)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        arm = Path(td) / "arm"
        (arm / "tests").mkdir(parents=True)
        (arm / "hand.py").write_text(HAND_SRC, encoding="utf-8")
        (arm / "tests" / "check.py").write_text(CHECK_SRC, encoding="utf-8")
        receipt = Path(td) / "out" / "receipt.jsonl"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--arm-dir",
                str(arm),
                "--hand-cmd",
                f'"{sys.executable}" hand.py',
                "--referee",
                f'"{sys.executable}" tests/check.py',
                "--receipt",
                str(receipt),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"dispatch exit {result.returncode}"

        rows = [
            json.loads(l)
            for l in receipt.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert len(rows) == 1, f"expected 1 receipt row, got {len(rows)}"
        row = rows[0]
        assert row["pass"] is True, "receipt row not pass"
        assert row["referee_exit"] == 0, f"referee_exit {row['referee_exit']}"
        assert row["referee_last_line"] == REFEREE_LINE, (
            f"referee line mangled: {ascii(row['referee_last_line'])}"
        )

        log_bytes = Path(row["log"]).read_bytes()
        log_text = log_bytes.decode("utf-8")  # must not raise
        assert HAND_MARK in log_text, "hand output missing from log"
        assert RDQ in log_text, "U+201D lost from captured hand output"
        assert "can't decode" not in log_text, "log holds a decode error, not hand output"
    return 0


if __name__ == "__main__":
    try:
        rc = main()
        print("PASS dispatch_fix")
        raise SystemExit(rc)
    except AssertionError as e:
        print(f"FAIL dispatch_fix: {e}")
        raise SystemExit(1)
