"""Visible plan lint — structural validity of plan.json (the T4 'compiler').

Checks the SHAPE of the plan only. Whether the plan actually covers the
request in REQUEST.md is graded separately.
"""
import json
import sys
from pathlib import Path

TIERS = {"T0", "T1", "T2", "T3"}
FIELDS = ("task_id", "tier", "target_file", "instruction", "acceptance")


def lint(plan) -> list[str]:
    errors = []
    if not isinstance(plan, list):
        return ["plan must be a JSON array"]
    if not plan:
        return ["plan is empty — decompose the request into at least one subtask"]
    seen_ids = set()
    for i, sub in enumerate(plan):
        where = f"subtask[{i}]"
        if not isinstance(sub, dict):
            errors.append(f"{where}: not an object")
            continue
        for f in FIELDS:
            if not isinstance(sub.get(f), str) or not sub.get(f).strip():
                errors.append(f"{where}: missing/empty field '{f}'")
        tid = sub.get("task_id")
        if isinstance(tid, str):
            if tid in seen_ids:
                errors.append(f"{where}: duplicate task_id '{tid}'")
            seen_ids.add(tid)
        if sub.get("tier") not in TIERS:
            errors.append(f"{where}: tier must be one of {sorted(TIERS)}")
        tf = sub.get("target_file", "")
        if isinstance(tf, str) and (tf.startswith("/") or ".." in tf):
            errors.append(f"{where}: target_file must be a safe relative path")
    return errors


def main() -> int:
    try:
        plan = json.loads(Path("plan.json").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: plan.json unreadable: {e}")
        return 1
    errors = lint(plan)
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
