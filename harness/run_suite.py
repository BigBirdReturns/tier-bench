from __future__ import annotations

import argparse
from pathlib import Path

from cost_guard import Tier
from harness.config import RunConfig
from harness.run_task import run_task

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True, choices=[t.name for t in Tier])
    ap.add_argument("--results", default="harness_results.jsonl")
    args = ap.parse_args()

    cfg = RunConfig(results_path=Path(args.results))

    tier = Tier[args.tier]
    tasks = sorted(Path("tasks").glob(f"{tier.name.lower()}_*.json"))

    for t in tasks:
        run_task(t, cfg)

if __name__ == "__main__":
    main()
