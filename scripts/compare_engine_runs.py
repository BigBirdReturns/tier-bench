#!/usr/bin/env python3
"""Compare two independently sealed ARC-C engine runs.

Literal model/rung bindings may differ across engines.  Comparability is based
on normalized rung roles plus the same source commit, task manifests, K and
packet contract.  The output reports agreement; it never silently merges rows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from validate_orchestration_run import validate_run  # noqa: E402


def _manifest_contract(run: dict) -> list[tuple]:
    return sorted((m.get("task_id"), m.get("path"), m.get("sha256"))
                  for m in run.get("task_manifests", []))


def _decision_contract(decision: dict | None) -> dict:
    decision = decision or {}
    return {key: decision.get(key) for key in
            ("state", "action", "route_to", "escalation_from", "abstained")}


def _task_spend(run: dict, task_id: str) -> dict:
    rows = [r for r in run.get("trials", []) if r.get("task_id") == task_id]
    return {
        "cost_usd": round(sum(float(r.get("spend", {}).get("cost_usd", 0) or 0)
                              for r in rows), 6),
        "cost_bases": sorted({r.get("spend", {}).get("cost_basis") for r in rows
                              if r.get("spend", {}).get("cost_basis")}),
        "trials": len(rows),
    }


def compare_runs(left: dict, right: dict) -> dict:
    le, re = left.get("engine", {}), right.get("engine", {})
    lp, rp = left.get("pairing", {}), right.get("pairing", {})
    result = {
        "pair_id": lp.get("pair_id"),
        "left_engine": le.get("engine_id"),
        "right_engine": re.get("engine_id"),
        "status": "incomparable",
        "reasons": [],
        "tasks": [],
    }

    if lp.get("independent_before_exchange") is not True or rp.get("independent_before_exchange") is not True:
        result["status"] = "contaminated"
        result["reasons"].append("at least one engine saw peer conclusions before sealing")
        return result
    if le.get("engine_id") == re.get("engine_id") or le.get("lineage") == re.get("lineage"):
        result["status"] = "invalid_pair"
        result["reasons"].append("peer evidence requires different engine IDs and provider lineages")
        return result

    shared = {
        "pair_id": (lp.get("pair_id"), rp.get("pair_id")),
        "source_commit": (lp.get("source_commit"), rp.get("source_commit")),
        "task_set": (left.get("task_set"), right.get("task_set")),
        "task_manifests": (_manifest_contract(left), _manifest_contract(right)),
        "normalized_rungs": (left.get("rungs"), right.get("rungs")),
        "k": (left.get("k"), right.get("k")),
    }
    for name, (a, b) in shared.items():
        if a != b:
            result["reasons"].append(f"{name} differs")
    if lp.get("peer_engine_id") != re.get("engine_id") or rp.get("peer_engine_id") != le.get("engine_id"):
        result["reasons"].append("pairing.peer_engine_id does not cross-reference the peer run")
    if lp.get("peer_lineage") != re.get("lineage") or rp.get("peer_lineage") != le.get("lineage"):
        result["reasons"].append("pairing.peer_lineage does not cross-reference the peer run")
    if result["reasons"]:
        return result
    if left.get("status") != "sealed" or right.get("status") != "sealed":
        result["status"] = "unpaired"
        result["reasons"].append("both independent runs must be sealed before comparison")
        return result

    ldec = {d.get("task_id"): d for d in left.get("decisions", [])}
    rdec = {d.get("task_id"): d for d in right.get("decisions", [])}
    agreements = 0
    for task_id in left.get("task_set", []):
        lc, rc = _decision_contract(ldec.get(task_id)), _decision_contract(rdec.get(task_id))
        agrees = lc == rc
        agreements += int(agrees)
        result["tasks"].append({
            "task_id": task_id,
            "agreement": agrees,
            "left_decision": lc,
            "right_decision": rc,
            "left_spend": _task_spend(left, task_id),
            "right_spend": _task_spend(right, task_id),
        })
    total = len(result["tasks"])
    result["status"] = "comparable"
    result["agreement"] = {"tasks": total, "agree": agreements,
                           "rate": (agreements / total) if total else None}
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare_engine_runs.py LEFT.json RIGHT.json", file=sys.stderr)
        return 2
    paths = [Path(arg) for arg in sys.argv[1:]]
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    problems = []
    for path, run in zip(paths, runs):
        problems.extend(f"{path.name}: {error}" for error in validate_run(run))
    if problems:
        print("FAIL — invalid input run(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    result = compare_runs(*runs)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "comparable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
