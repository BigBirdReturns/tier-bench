#!/usr/bin/env python3
"""Burn report: calibration report from cost sentinel state."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("experiments/breadth/run/.sentinel_state"),
    )
    args = parser.parse_args()

    state_dir = args.state_dir

    # Collect valid sessions
    sessions = []
    if state_dir.exists():
        for json_file in state_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sid = json_file.stem
                    cost = data.get("cost_usd", 0.0)
                    tier = data.get("tier")
                    sessions.append((sid, cost, tier))
            except (json.JSONDecodeError, ValueError):
                pass

    if not sessions:
        print("no sessions")
        return 0

    # Sort: cost_usd DESCENDING, session id ASCENDING
    sessions.sort(key=lambda x: (-x[1], x[0]))

    # Print rows
    for sid, cost, tier in sessions:
        tier_str = tier if tier is not None else "-"
        print(f"{sid[:8]}  ${cost:.2f}  {tier_str}")

    # Summary
    print()
    costs = sorted([cost for _, cost, _ in sessions])
    n = len(costs)
    total = sum(costs)

    # Nearest-rank percentile: ceil(p/100 * N) - 1
    median_idx = math.ceil(0.5 * n) - 1
    p90_idx = math.ceil(0.9 * n) - 1
    median = costs[median_idx]
    p90 = costs[p90_idx]

    print(f"sessions: {n}")
    print(f"total: ${total:.2f}")
    print(f"median: ${median:.2f}")
    print(f"p90: ${p90:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
