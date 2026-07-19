#!/usr/bin/env python3
"""Frozen referee for X2: crate_new.py --list. Exit 0 = PASS."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
SCRIPT = ROOT / "scripts" / "crate_new.py"


def run(extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=60,
    )


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "crates"
        d.mkdir()
        (d / "alpha_v1").mkdir()
        (d / "beta_v1").mkdir()
        (d / "notes.txt").write_text("not a dir", encoding="utf-8")
        before = sorted(p.name for p in d.iterdir())

        # 1. --list without --name: exit 0, dirs listed one per line, nothing created
        r = run(["--list", "--dir", str(d)])
        if r.returncode != 0:
            fail(f"--list exit {r.returncode}: {(r.stderr or '').strip()[:200]}")
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        names = {Path(l).name for l in lines}
        if names != {"alpha_v1", "beta_v1"}:
            fail(f"--list printed {sorted(names)}, want exactly ['alpha_v1', 'beta_v1']")
        if len(lines) != 2:
            fail(f"--list printed {len(lines)} non-empty lines, want 2 (one name per line)")
        after = sorted(p.name for p in d.iterdir())
        if after != before:
            fail(f"--list changed the directory: {before} -> {after}")

        # 2. --list on an empty dir: exit 0
        empty = Path(td) / "empty"
        empty.mkdir()
        r = run(["--list", "--dir", str(empty)])
        if r.returncode != 0:
            fail(f"--list on empty dir exit {r.returncode}")
        if [l for l in r.stdout.splitlines() if l.strip()]:
            fail("--list on empty dir printed spurious lines")

        # 3. Creation path unchanged
        r = run(["--name", "gamma_v1", "--dir", str(d)])
        if r.returncode != 0:
            fail(f"create path broke: exit {r.returncode}: {(r.stderr or '').strip()[:200]}")
        crate = d / "gamma_v1"
        for fname in ("000.000.INDEX.md", "010.100.TASK.md", "020.100.ACCEPTANCE.md"):
            if not (crate / fname).is_file():
                fail(f"create path no longer writes {fname}")

        # 4. Existing-crate refusal unchanged
        r = run(["--name", "gamma_v1", "--dir", str(d)])
        if r.returncode == 0:
            fail("creating an existing crate no longer fails")

    print("PASS: X2 referee ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
