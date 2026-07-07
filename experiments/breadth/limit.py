#!/usr/bin/env python3
"""
Approaching the limit — checkpoint, then hand the human an honest decision.

Two different "limits" get conflated, and the escalation call depends on which:

  * QUOTA limit — you're running out of how much of the model your CURRENT access
    tier lets you run. Escalating access (pro -> max) buys more quota, so it CAN
    let you finish mapping the residual. This is a real escalate-y/n decision.

  * CAPABILITY ceiling — a task walls even at the top effort rung. More access buys
    nothing here: it's the model's ceiling, not a quota wall. The answer is never
    "pay for more access" — it's "route to the harness (search/decompose) or mark
    it genuinely hard / unverifiable."

`decision_packet` keeps these apart so "escalate access?" is answered by *is there
residual I could still map, and won't it fit in my remaining quota* — not by a task
being hard. Designed right (Sonnet floor + effort cascade), the residual is empty
before the quota runs out and the honest recommendation is DO NOT ESCALATE.
"""
from __future__ import annotations

UNSOLVED = "UNSOLVED"


def budget_status(rows: list[dict], quota_usd: float | None = None,
                  quota_calls: int | None = None, warn_frac: float = 0.8) -> dict:
    """Usage against the current access tier's quota. `approaching` at warn_frac."""
    spent = round(sum(float(r.get("cost_usd", 0) or 0) for r in rows), 6)
    calls = len(rows)
    fracs = []
    if quota_usd:
        fracs.append(spent / quota_usd)
    if quota_calls:
        fracs.append(calls / quota_calls)
    frac = round(max(fracs), 3) if fracs else 0.0
    return {
        "spent_usd": spent, "calls": calls,
        "quota_usd": quota_usd, "quota_calls": quota_calls,
        "frac_used": frac,
        "remaining_usd": round(quota_usd - spent, 6) if quota_usd else None,
        "approaching": frac >= warn_frac,
        "exhausted": frac >= 1.0,
    }


def decision_packet(breadth: dict, all_tasks: list[str], budget: dict,
                    top_rung: str, est_usd_per_task: float) -> dict:
    """The human escalation decision, computed — not vibes.

    breadth: output of escalate.breadth_map. all_tasks: the full planned set.
    top_rung: the highest effort rung (e.g. 'claude-fable-5@max'). est_usd_per_task:
    rough cost to run one unmapped task up the remaining ladder.
    """
    tasks = breadth.get("tasks", {})
    mapped = set(tasks)
    unmapped = [t for t in all_tasks if t not in mapped]  # never run to a clear or a max wall

    # capability ceilings: reached the top rung and still didn't clear — access won't help
    ceilings = [t for t, info in tasks.items()
                if str(info.get("min_sufficient_tier", "")).startswith(UNSOLVED)
                and top_rung in (info.get("measured") or {})]

    # residual worth spending more quota on = unmapped tasks (mapping them needs runs you
    # haven't done yet). Ceilings are NOT residual — no quota fixes them.
    proj_finish_usd = round(len(unmapped) * est_usd_per_task, 4)
    remaining = budget.get("remaining_usd")
    wont_fit = remaining is not None and proj_finish_usd > remaining

    if not unmapped:
        rec, why = "DO NOT ESCALATE", (
            "the map is complete within current access — everything reached a clear or a "
            "capability ceiling. You have the best baseline; escalating access buys nothing.")
    elif budget["approaching"] and wont_fit:
        rec, why = "ESCALATE ACCESS", (
            f"{len(unmapped)} task(s) still unmapped and finishing them (~${proj_finish_usd}) "
            f"exceeds your remaining quota (${remaining}). More access = more quota to finish "
            f"the map. This is a quota decision, not a difficulty one.")
    else:
        rec, why = "DO NOT ESCALATE (yet)", (
            f"{len(unmapped)} unmapped task(s) but ~${proj_finish_usd} still fits remaining "
            f"quota (${remaining}). Finish within current access first.")

    return {
        "recommendation": rec,
        "why": why,
        "budget": budget,
        "mapped_tasks": len(mapped),
        "unmapped_residual": unmapped,
        "capability_ceilings": {
            "tasks": ceilings,
            "note": "access does NOT help these — route to the harness (search/decompose) "
                    "or mark genuinely hard / unverifiable.",
        },
        "projected_finish_usd": proj_finish_usd,
    }


if __name__ == "__main__":
    import argparse, json  # noqa: E401
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from experiments.breadth.ledger import load  # noqa: E402
    ap = argparse.ArgumentParser(description="Budget status + escalation decision packet.")
    ap.add_argument("ledger")
    ap.add_argument("--breadth", help="json from escalate.py", default=None)
    ap.add_argument("--all-tasks", default="", help="comma-separated full task set")
    ap.add_argument("--quota-usd", type=float, default=None)
    ap.add_argument("--top-rung", default="claude-fable-5@max")
    ap.add_argument("--est-usd-per-task", type=float, default=1.8)
    a = ap.parse_args()
    rows = load(a.ledger)
    b = budget_status(rows, quota_usd=a.quota_usd)
    print(json.dumps(b, indent=2))
    if a.breadth:
        breadth = json.loads(Path(a.breadth).read_text())
        allt = [t for t in a.all_tasks.split(",") if t] or list(breadth.get("tasks", {}))
        print(json.dumps(decision_packet(breadth, allt, b, a.top_rung, a.est_usd_per_task), indent=2))
