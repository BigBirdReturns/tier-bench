#!/usr/bin/env python3
"""Export breadth-run ledger rows into the community contribution pipeline.

The site's comparer, aggregate.json, and cheatsheet all read data/results/*.jsonl
— the one door in (contribute.py). The breadth self-run's solve trials never
went through that door, so the public surfaces stayed empty while the ledger
filled up. This bridges them: ledger rows -> harness_results rows -> packaged,
validated contribution.

Only rows that qualify are exported: phase=baseline (solve trials), a definitive
pass/fail outcome, and a task_id that exists in tasks/*.json (the contribution
schema's own rule — tier-uplift breadth cells live in waterline.json instead).

    python scripts/export_breadth_results.py --as bigbirdreturns [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def task_tiers() -> dict[str, str]:
    out = {}
    for mp in (REPO / "tasks").glob("*.json"):
        raw = json.loads(mp.read_text(encoding="utf-8"))
        out[raw["task_id"]] = raw["tier"]
    return out


def export_rows() -> list[dict]:
    tiers = task_tiers()
    rows = []
    for line in (REPO / "experiments/breadth/run/ledger.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("phase") != "baseline" or r.get("outcome") not in ("pass", "fail"):
            continue
        if r.get("task_id") not in tiers:
            continue  # tier-uplift breadth cells — surfaced via waterline.json, not this pipeline
        rows.append({
            "task_id": r["task_id"],
            "tier": tiers[r["task_id"]],
            "model": r["model"],
            "pass": r["outcome"] == "pass",
            "actual_cost": round(float(r.get("cost_usd", 0.0)), 6),
            "effort": r.get("effort", ""),
            "trial": r.get("trial", 0),
            "cost_basis": "real-billed" if "REAL billed" in r.get("note", "") else "shadow-estimated",
            "hidden_graded": "hidden" in r.get("note", "").lower()
                              or bool((r.get("extra") or {}).get("validators", {}).get("hidden_ok") is not None),
            "source": "breadth-selfrun ledger.jsonl",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as", dest="handle", default="bigbirdreturns")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = export_rows()
    by_model: dict[str, int] = {}
    for r in rows:
        by_model[r["model"]] = by_model.get(r["model"], 0) + 1
    print(f"exportable rows: {len(rows)}  by model: {by_model}")
    if a.dry_run:
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
        tmp = f.name
    p = subprocess.run([sys.executable, str(REPO / "scripts/contribute.py"),
                        "--results", tmp, "--as", a.handle], cwd=REPO,
                       capture_output=True, text=True)
    print(p.stdout.strip() or p.stderr.strip())
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
