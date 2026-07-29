#!/usr/bin/env python3
"""Run the public Interaction Floor reference conformance transaction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from estate_lab.cli import main  # noqa: E402


if __name__ == "__main__":
    output = ROOT / ".floor-conformance"
    status = main(["floor", "validate"])
    if status != 0:
        raise SystemExit(status)
    raise SystemExit(main(["floor", "test", "--output", str(output)]))
