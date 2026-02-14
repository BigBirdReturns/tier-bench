from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

def run(cmd: list[str]) -> int:
    p = subprocess.run(cmd, text=True)
    return p.returncode

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True, choices=["T0", "T1", "T2", "T3", "T4", "T5"])
    ap.add_argument("--results", default="harness_results.jsonl")
    args = ap.parse_args()

    if run(["python", "scripts/preflight.py"]) != 0:
        return 1

    rc = run(["python", "harness/run_suite.py", "--tier", args.tier, "--results", args.results])
    if rc != 0:
        return rc

    print("")
    print("METRICS")
    return run(["python", "scripts/compute_metrics.py", "--results", args.results])

if __name__ == "__main__":
    raise SystemExit(main())
