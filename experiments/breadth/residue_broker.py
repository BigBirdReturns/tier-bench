#!/usr/bin/env python3
"""Pure residue routing policy: floor first, escalate only on a measured wall.

The broker never calls a model and never grades a candidate.  It reduces sealed
trial receipts into the next allowed action.  Keeping this layer pure makes the
routing policy independently testable and prevents a solver from changing the
rule that decides whether it earned escalation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DECISIVE_OUTCOMES = {"pass", "fail"}


def rung_evidence(trials: list[dict], rung: str, k: int) -> dict:
    """Return the evidence state for one rung.

    Error/partial rows remain visible in ``observations`` but do not buy a wall
    or a clear.  A wall is at least K failures and zero passes; a clear is at
    least K passes and zero failures.  Mixed decisive evidence is unstable.
    """
    rows = [r for r in trials if r.get("rung") == rung]
    outcomes = [r.get("verdict", {}).get("outcome") for r in rows]
    decisive_outcomes = [outcome for outcome in outcomes if outcome in DECISIVE_OUTCOMES]
    passes = decisive_outcomes.count("pass")
    failures = decisive_outcomes.count("fail")
    decisive = passes + failures
    window = decisive_outcomes[-k:]
    window_passes = window.count("pass")
    window_failures = window.count("fail")
    if decisive == 0:
        state = "unmeasured" if not rows else "collecting"
    elif len(window) < k:
        state = "collecting"
    elif window_passes == k:
        state = "clears"
    elif window_failures == k:
        state = "wall"
    elif window_passes and window_failures:
        state = "unstable"
    else:
        state = "collecting"
    return {
        "rung": rung,
        "observations": len(rows),
        "decisive": decisive,
        "passes": passes,
        "failures": failures,
        "window_size": len(window),
        "window_passes": window_passes,
        "window_failures": window_failures,
        "required_k": k,
        "state": state,
    }


def decision_for_task(trials: list[dict], task_id: str, rungs: list[str], k: int) -> dict:
    """Compute the only route the residue policy permits for ``task_id``."""
    task_rows = sorted(
        (r for r in trials if r.get("task_id") == task_id),
        key=lambda r: (r.get("sequence", 0), r.get("trial_id", "")),
    )
    evidence: list[dict] = []
    escalation_from = None

    for index, rung in enumerate(rungs):
        ev = rung_evidence(task_rows, rung, k)
        evidence.append(ev)
        state = ev["state"]

        if state == "unmeasured":
            escalating = escalation_from is not None
            return {
                "task_id": task_id,
                "state": "unmeasured",
                "action": "escalate" if escalating else "route",
                "route_to": rung,
                "escalation_from": escalation_from,
                "abstained": False,
                "reason": (f"prior rung {escalation_from} is a measured 0/K wall; "
                           f"dispatch the next rung" if escalating else
                           "start at the cheapest unmeasured rung"),
                "evidence": evidence,
            }
        if state == "collecting":
            return {
                "task_id": task_id,
                "state": "collecting",
                "action": "collect_more",
                "route_to": rung,
                "escalation_from": escalation_from,
                "abstained": False,
                "reason": "fewer than K decisive receipts; errors and partials do not buy escalation",
                "evidence": evidence,
            }
        if state == "unstable":
            return {
                "task_id": task_id,
                "state": "unstable",
                "action": "collect_more",
                "route_to": rung,
                "escalation_from": None,
                "abstained": True,
                "reason": "mixed K-window evidence abstains from a conclusion and collects another same-rung trial",
                "evidence": evidence,
            }
        if state == "clears":
            return {
                "task_id": task_id,
                "state": "cleared",
                "action": "seal",
                "route_to": rung,
                "escalation_from": escalation_from,
                "abstained": False,
                "reason": "K-of-K decisive receipts clear this rung",
                "evidence": evidence,
            }

        # A wall is the only state that earns the next rung.
        if index + 1 < len(rungs):
            escalation_from = rung
            continue
        return {
            "task_id": task_id,
            "state": "wall",
            "action": "abstain",
            "route_to": None,
            "escalation_from": rung,
            "abstained": True,
            "reason": "top available rung is a measured wall; access escalation is a human gate",
            "evidence": evidence,
        }

    raise ValueError("rungs must not be empty")


def decisions_for_run(run: dict) -> list[dict]:
    """Return deterministic decisions in task-set order."""
    return [
        decision_for_task(run.get("trials", []), task_id, run["rungs"], run["k"])
        for task_id in run["task_set"]
    ]


def prior_rows(trials: list[dict], sequence: int) -> list[dict]:
    """Rows admissible as routing evidence before a trial was dispatched."""
    return [r for r in trials if isinstance(r.get("sequence"), int) and r["sequence"] < sequence]


def route_was_allowed(run: dict, trial: dict) -> tuple[bool, dict]:
    """Check a recorded dispatch against evidence available at dispatch time."""
    decision = decision_for_task(
        prior_rows(run.get("trials", []), trial["sequence"]),
        trial["task_id"],
        run["rungs"],
        run["k"],
    )
    return decision.get("route_to") == trial.get("rung") and decision["action"] in {
        "route", "collect_more", "escalate"
    }, decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="residue run JSON")
    parser.add_argument("--write", action="store_true", help="replace recorded decisions atomically")
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf-8"))
    decisions = decisions_for_run(run)
    if args.write:
        run["decisions"] = decisions
        tmp = args.run.with_suffix(args.run.suffix + ".tmp")
        tmp.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        tmp.replace(args.run)
        print(f"updated {args.run} with {len(decisions)} broker decision(s)")
    else:
        print(json.dumps(decisions, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
