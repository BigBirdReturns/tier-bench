#!/usr/bin/env python3
"""Driver-authored referee for crate crate_new_v1. Frozen; hands run, never edit."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/crate_new.py"


def run(name, d):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--name", name, "--dir", str(d)],
        capture_output=True, text=True, timeout=60,
    )


def main() -> int:
    assert SCRIPT.exists(), "scripts/crate_new.py does not exist"
    with tempfile.TemporaryDirectory() as td:
        p = run("demo_v1", td)
        assert p.returncode == 0, f"exit {p.returncode}: {p.stderr}"
        assert p.stdout.strip().startswith("created: "), p.stdout
        c = Path(td) / "demo_v1"
        idx = (c / "000.000.INDEX.md").read_text(encoding="utf-8")
        task = (c / "010.100.TASK.md").read_text(encoding="utf-8")
        acc = (c / "020.100.ACCEPTANCE.md").read_text(encoding="utf-8")
        assert idx.splitlines()[0] == "# 000.000 Crate index — demo_v1"
        assert task.splitlines()[0] == "# 010.100 Task — demo_v1"
        assert acc.splitlines()[0] == "# 020.100 Acceptance"
        assert "<ALLOWED_FILE>" in idx and "<REFEREE_CMD>" in idx
        assert "<SPEC>" in task and "<REFEREE_CMD>" in acc
        assert len(list(c.iterdir())) == 3, "exactly three files"
        p2 = run("demo_v1", td)
        assert p2.returncode == 1 and p2.stdout.strip().startswith("exists: "), (
            p2.returncode, p2.stdout)
    print("PASS crate_new")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL crate_new: {e}")
        raise SystemExit(1)
