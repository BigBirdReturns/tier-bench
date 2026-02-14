from __future__ import annotations

import argparse
from pathlib import Path

from harness.metrics import compute

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="harness_results.jsonl")
    args = ap.parse_args()

    stats = compute(Path(args.results))
    rows = []
    for (model, tier), s in stats.items():
        rows.append((tier, model, s.attempts, s.successes, round(s.success_rate, 3), round(s.avg_cost_per_attempt, 6), round(s.cost_per_success, 6) if s.cost_per_success != float("inf") else "inf"))
    rows.sort(key=lambda r: (r[0], r[6] if isinstance(r[6], (int, float)) else 1e9))

    print("tier\tmodel\tattempts\tsuccesses\tsuccess_rate\tavg_cost\tcost_per_success")
    for r in rows:
        print("\t".join(map(str, r)))

if __name__ == "__main__":
    main()
