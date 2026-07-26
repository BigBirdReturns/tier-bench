#!/usr/bin/env python3
"""Pure ARC-C routing policy: floor first, escalate only on a measured wall.

The executable remains at its historical path, while the policy now lives in
``tier_runner.residue_policy`` so Monster Wrangler and the offline validators use
one implementation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tier_runner.residue_policy import (
    DECISIVE_OUTCOMES,
    decision_for_task,
    decisions_for_run,
    prior_rows,
    route_was_allowed,
    rung_evidence,
)

__all__ = [
    "DECISIVE_OUTCOMES",
    "decision_for_task",
    "decisions_for_run",
    "prior_rows",
    "route_was_allowed",
    "rung_evidence",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="ARC-C run JSON")
    parser.add_argument("--write", action="store_true", help="replace recorded decisions atomically")
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf-8"))
    decisions = decisions_for_run(run)
    if args.write:
        run["decisions"] = decisions
        temporary = args.run.with_suffix(args.run.suffix + ".tmp")
        temporary.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.run)
        print(f"updated {args.run} with {len(decisions)} decision(s)")
    else:
        print(json.dumps(decisions, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
