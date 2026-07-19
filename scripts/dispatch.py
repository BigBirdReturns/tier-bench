#!/usr/bin/env python3
"""Hand dispatcher: run a hand command, referee the result, append receipt row."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def count_existing_rows(receipt_path: Path) -> int:
    """Count existing JSON lines in receipt file."""
    if not receipt_path.exists():
        return 0
    try:
        lines = receipt_path.read_text(encoding="utf-8").splitlines()
        return len([l for l in lines if l.strip()])
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run hand command and referee result")
    parser.add_argument("--arm-dir", required=True, help="Working directory for commands")
    parser.add_argument("--hand-cmd", required=True, help="Hand command to run")
    parser.add_argument("--referee", required=True, help="Referee command to run")
    parser.add_argument("--receipt", required=True, help="Receipt file path")
    args = parser.parse_args()

    arm_dir = Path(args.arm_dir)
    receipt_path = Path(args.receipt)

    # Create receipt directory if needed
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    # Count existing rows to determine log file number
    n = count_existing_rows(receipt_path) + 1
    log_path = receipt_path.parent / f"{receipt_path.stem}_{n}.log"

    # Run hand command, capture output
    try:
        hand_result = subprocess.run(
            args.hand_cmd,
            shell=True,
            cwd=arm_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        hand_output = hand_result.stdout + hand_result.stderr
    except Exception as e:
        hand_output = str(e)
        hand_result = None

    # Write log file
    log_path.write_text(hand_output, encoding="utf-8")

    # Run referee command, capture output
    try:
        referee_result = subprocess.run(
            args.referee,
            shell=True,
            cwd=arm_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        referee_exit = referee_result.returncode
        referee_output = referee_result.stdout
    except Exception as e:
        referee_exit = 1
        referee_output = str(e)

    # Extract last non-empty line from referee output
    referee_lines = [l for l in referee_output.splitlines() if l.strip()]
    referee_last_line = referee_lines[-1] if referee_lines else ""

    # Determine pass/fail
    pass_flag = (referee_exit == 0)

    # Build receipt row
    row = {
        "arm_dir": str(arm_dir),
        "hand_cmd": args.hand_cmd,
        "pass": pass_flag,
        "referee_exit": referee_exit,
        "referee_last_line": referee_last_line,
        "log": str(log_path),
    }

    # Append to receipt file
    try:
        with open(receipt_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        print(f"Error writing receipt: {e}", file=sys.stderr)
        return 1

    # Exit with appropriate code
    return 0 if pass_flag else 2


if __name__ == "__main__":
    sys.exit(main())
