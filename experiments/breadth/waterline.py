#!/usr/bin/env python3
"""The waterline, as an instrument: given a task, the cheapest MEASURED thing
that should do it — settled work routes cheap, judgment residue is named and
priced, missing evidence says missing. Zero spend; reads run/waterline.json.

    python experiments/breadth/waterline.py --explain
    python experiments/breadth/waterline.py --task task02_wildcard
    python experiments/breadth/waterline.py --json
    python experiments/breadth/waterline.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WL = Path(__file__).resolve().parent / "run" / "waterline.json"
REQUIRED = ("status", "cheapest_measured", "rung", "score", "evidence_layer",
            "cost_usd_per_trial", "cost_basis", "caveats", "next_allowed_action")


def load() -> dict:
    return json.loads(WL.read_text(encoding="utf-8"))


def check(w: dict) -> list[str]:
    errors: list[str] = []
    corner = Path(__file__).resolve().parent / "run" / "known_corner.jsonl"
    layers = {json.loads(l)["layer"] for l in corner.read_text().splitlines() if l.strip()}
    for section in ("settled_floor", "judgment_residue"):
        for tid, row in w.get(section, {}).items():
            for f in REQUIRED:
                if f not in row:
                    errors.append(f"{tid}: missing required field '{f}'")
            if row.get("evidence_layer") not in layers:
                errors.append(f"{tid}: evidence_layer '{row.get('evidence_layer')}' not in known_corner.jsonl")
            if section == "judgment_residue":
                if not row.get("residue_name"):
                    errors.append(f"{tid}: judgment_residue row must NAME the residue")
                if "settled" in str(row.get("status", "")) and not row.get("score"):
                    errors.append(f"{tid}: claims settled without a score")
            if row.get("cost_basis") not in ("real-billed", "shadow-estimated"):
                errors.append(f"{tid}: cost_basis must be real-billed or shadow-estimated")
    return errors


def explain_task(w: dict, task_id: str) -> str:
    for section, label in (("settled_floor", "settled"), ("judgment_residue", "judgment_residue")):
        row = w.get(section, {}).get(task_id)
        if row:
            lines = [task_id, f"  class: {label}"]
            if section == "judgment_residue":
                lines += [f"  residue: {row['residue_name']}",
                          f"  floor status: {row['floor_instability']}"]
            lines += [
                f"  cheapest measured: {row['cheapest_measured']} @ {row['rung']}",
                f"  score: {row['score']}",
                f"  cost: ~${row['cost_usd_per_trial']}/trial ({row['cost_basis']})",
                f"  evidence: {row['evidence_layer']}",
                f"  next allowed spend: {row['next_allowed_action']}",
            ]
            lines += [f"  caveat: {c}" for c in row.get("caveats", [])]
            return "\n".join(lines)
    return (f"{task_id}\n  class: UNMEASURED\n  routing: no measured row exists — "
            "say 'missing', do not guess. To measure: RUNBOOK.md floor protocol (hidden graders only).")


def explain(w: dict) -> str:
    out = ["THE WATERLINE — cheapest measured execution path per task",
           "(anything not listed is unmeasured; evidence layers in known_corner.jsonl)", ""]
    for tid in w.get("settled_floor", {}):
        out += [explain_task(w, tid), ""]
    for tid in w.get("judgment_residue", {}):
        out += [explain_task(w, tid), ""]
    a = w.get("adjudications", {})
    if a:
        out.append("adjudications (evidence-class corrections, not capability rows):")
        out += [f"  {k}: {v['classification']} ({v['evidence']})" for k, v in a.items()]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--task")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    w = load()
    if a.check:
        errors = check(w)
        for e in errors:
            print(f"CHECK FAIL: {e}")
        print("WATERLINE CHECK " + ("FAILED" if errors else "OK — every claim carries status, "
              "score, cost basis, and a real sediment layer"))
        return 1 if errors else 0
    if a.json:
        print(json.dumps(w, indent=2))
    elif a.task:
        print(explain_task(w, a.task))
    else:
        print(explain(w))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
