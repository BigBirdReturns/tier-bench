"""Pure frontier-residue routing policy.

The policy consumes sealed trial receipts and returns the next permitted action.
It never calls a model, grades a candidate, or changes task state.  A decisive
wall is K failures and zero passes in the latest K decisive receipts.  Errors
remain visible but never buy escalation.
"""
from __future__ import annotations

DECISIVE_OUTCOMES = {"pass", "fail"}


def rung_evidence(trials: list[dict], rung: str, k: int) -> dict:
    """Return the evidence state for one rung."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    rows = [row for row in trials if row.get("rung") == rung]
    outcomes = [row.get("verdict", {}).get("outcome") for row in rows]
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
    """Compute the only floor-first route currently permitted for ``task_id``."""
    if not rungs:
        raise ValueError("rungs must not be empty")
    if len(set(rungs)) != len(rungs):
        raise ValueError("rungs must be unique")
    task_rows = sorted(
        (row for row in trials if row.get("task_id") == task_id),
        key=lambda row: (row.get("sequence", 0), row.get("trial_id", "")),
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
                "reason": (
                    f"prior rung {escalation_from} is a measured 0/K wall; dispatch the next rung"
                    if escalating
                    else "start at the cheapest unmeasured rung"
                ),
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

    raise AssertionError("unreachable")


def decisions_for_run(run: dict) -> list[dict]:
    """Return deterministic decisions in task-set order."""
    return [
        decision_for_task(run.get("trials", []), task_id, run["rungs"], run["k"])
        for task_id in run["task_set"]
    ]


def prior_rows(trials: list[dict], sequence: int) -> list[dict]:
    """Rows admissible as routing evidence before a trial was dispatched."""
    return [
        row
        for row in trials
        if isinstance(row.get("sequence"), int) and row["sequence"] < sequence
    ]


def route_was_allowed(run: dict, trial: dict) -> tuple[bool, dict]:
    """Check a recorded dispatch against evidence available at dispatch time."""
    decision = decision_for_task(
        prior_rows(run.get("trials", []), trial["sequence"]),
        trial["task_id"],
        run["rungs"],
        run["k"],
    )
    return decision.get("route_to") == trial.get("rung") and decision["action"] in {
        "route",
        "collect_more",
        "escalate",
    }, decision
