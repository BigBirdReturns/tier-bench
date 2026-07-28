#!/usr/bin/env python3
"""Run the retained Estate Lab proof from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from estate_lab.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(
        main(
            [
                "run-all",
                "--manifest",
                str(ROOT / "estate_lab" / "fixtures" / "estate.example.json"),
                "--scenario-dir",
                str(ROOT / "estate_lab" / "fixtures" / "scenarios"),
                "--output",
                str(ROOT / ".estate-lab-runs"),
            ]
        )
    )
