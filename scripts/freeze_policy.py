#!/usr/bin/env python3
"""
Freeze captured driver decisions into an immutable policy snapshot.

    python scripts/freeze_policy.py v1              # write driver/policy/v1/
    python scripts/freeze_policy.py v1 --dry-run    # show what would freeze

Reads driver_decisions.jsonl (populated by running the benchmark with
TIER_BENCH_CAPTURE_POLICY=1 while a real driver is set). Refuses to overwrite an
existing version — a change is a new version. See driver/policy/README.md.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness.driver_policy import DECISIONS_DEFAULT, _load_decisions, build_policy, freeze


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="snapshot version, e.g. v1")
    ap.add_argument("--decisions", default=str(DECISIONS_DEFAULT))
    ap.add_argument("--dry-run", action="store_true", help="show the policy; write nothing")
    a = ap.parse_args()

    decisions = _load_decisions(a.decisions)
    if not decisions:
        sys.exit(f"no decisions in {a.decisions} — run the benchmark with "
                 f"TIER_BENCH_CAPTURE_POLICY=1 and a driver set first.")
    policy = build_policy(decisions)
    passed = sum(1 for d in decisions if d.get("passed"))
    print(f"{len(decisions)} decisions ({passed} passed) -> {len(policy)} policy entries")
    for v in policy.values():
        print(f"  {v['signature']}  ->  " + " · ".join(v["plan"]) + f"   (support {v['support']}, from {v['from_drivers']})")
    if a.dry_run:
        print("(dry run — nothing written)")
        return
    dest = freeze(a.version, a.decisions)
    print(f"froze {dest}  (immutable)")


if __name__ == "__main__":
    main()
