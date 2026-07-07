#!/usr/bin/env python3
"""
Escalate on a measured ceiling — never on a hunch.

The question this answers: when you point a big model (Fable/max) at a project on
an escalating billing cascade, how do you make the jump from cheap → pro → max a
*true need* instead of trial-and-error? By refusing to escalate a task until the
current rung has hit a **reproducible** wall, and the next rung **reproducibly**
clears it. One miss is noise; K-of-K misses is a ceiling. That single distinction
is the whole guardrail.

Inputs are trial rows (usually derived from the token ledger):
    {"task_id": "...", "tier": "cheap", "outcome": "pass"|"fail", "trial": 0, ...}
Each (task, tier) should have K trials — ceilings are not measured from one run.

The output is the **breadth map**: for every task, the cheapest tier that clears
it reliably, the cost there, and — where escalation was forced — the K/K ceiling
that justified it. Sum the per-task minimum and you have the BEST baseline: the
model's full breadth mapped at the true floor price, every dollar of escalation
backed by evidence you can point at.

    python experiments/breadth/escalate.py trials.jsonl --tiers cheap,mid,frontier,max \
        --cost cheap=0.03,mid=0.13,frontier=0.20,max=0.63
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

DEFAULT_TIERS = ["cheap", "mid", "frontier", "max"]


def _rates(rows: list[dict]) -> dict:
    """(task, tier) -> {trials, passes, pass_rate}."""
    agg: dict[tuple, list] = defaultdict(list)
    for r in rows:
        agg[(r["task_id"], r["tier"])].append(1 if r.get("outcome") == "pass" else 0)
    return {k: {"trials": len(v), "passes": sum(v), "pass_rate": (sum(v) / len(v)) if v else 0.0}
            for k, v in agg.items()}


def classify(pass_rate: float, clear_thresh: float, wall_thresh: float) -> str:
    """clears | wall | unstable. 'unstable' means MORE TRIALS, not escalation."""
    if pass_rate >= clear_thresh:
        return "clears"
    if pass_rate <= wall_thresh:
        return "wall"
    return "unstable"


def breadth_map(rows: list[dict], tiers: list[str], cost: dict[str, float],
                clear_thresh: float = 1.0, wall_thresh: float = 0.0) -> dict:
    """The frontier: cheapest reliably-clearing tier per task + escalation evidence.

    clear_thresh=1.0 -> a tier only 'clears' a task if it passes EVERY trial.
    wall_thresh=0.0  -> a tier is a 'wall' only if it fails EVERY trial.
    Anything between is 'unstable': the honest verdict is run more trials, not pay more.
    """
    rates = _rates(rows)
    order = {t: i for i, t in enumerate(tiers)}
    tasks = sorted({t for (t, _) in rates})
    per_task = {}
    escalations = []
    baseline_cost = 0.0
    naive_max_cost = 0.0
    top = tiers[-1]

    for task in tasks:
        seen = [(t, rates[(task, t)]) for t in tiers if (task, t) in rates]
        seen.sort(key=lambda x: order[x[0]])
        min_tier = None
        for t, r in seen:
            if classify(r["pass_rate"], clear_thresh, wall_thresh) == "clears":
                min_tier = t
                break
        # record any need-driven escalation: a wall at T immediately below a clear at T+1
        for i in range(len(seen) - 1):
            t, r = seen[i]
            tn, rn = seen[i + 1]
            c_here = classify(r["pass_rate"], clear_thresh, wall_thresh)
            c_next = classify(rn["pass_rate"], clear_thresh, wall_thresh)
            if c_here == "wall" and c_next == "clears":
                escalations.append({
                    "task_id": task, "from": t, "to": tn,
                    "evidence": f"{r['passes']}/{r['trials']} at {t} (wall) -> "
                                f"{rn['passes']}/{rn['trials']} at {tn} (clears)",
                    "justified": True,
                })
            elif c_here == "unstable":
                escalations.append({
                    "task_id": task, "from": t, "to": tn,
                    "evidence": f"{r['passes']}/{r['trials']} at {t} is UNSTABLE — "
                                f"run more trials before escalating",
                    "justified": False,
                })
        cmin = cost.get(min_tier, 0.0) if min_tier else float("nan")
        cmax = cost.get(top, 0.0)
        if min_tier:
            baseline_cost += cmin
        naive_max_cost += cmax
        per_task[task] = {
            "min_sufficient_tier": min_tier or "UNSOLVED at every measured tier",
            "cost_at_min": cmin,
            "cost_if_max_everywhere": cmax,
            "waste_avoided": round(cmax - cmin, 6) if min_tier else 0.0,
            "measured": {t: f"{rates[(task,t)]['passes']}/{rates[(task,t)]['trials']}"
                         for t in tiers if (task, t) in rates},
        }

    return {
        "tiers": tiers,
        "tasks": per_task,
        "escalations": escalations,
        "baseline_cost_usd": round(baseline_cost, 6),          # cheapest-that-clears, summed
        "naive_max_everywhere_usd": round(naive_max_cost, 6),  # what running max blindly costs
        "saved_vs_naive_usd": round(naive_max_cost - baseline_cost, 6),
        "unjustified_escalations": [e for e in escalations if not e["justified"]],
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Compute the breadth map / escalation frontier.")
    ap.add_argument("trials", help="jsonl of {task_id, tier, outcome} trial rows")
    ap.add_argument("--tiers", default=",".join(DEFAULT_TIERS))
    ap.add_argument("--cost", default="", help="tier=usd,tier=usd (per-task cost at each tier)")
    ap.add_argument("--clear-thresh", type=float, default=1.0)
    ap.add_argument("--wall-thresh", type=float, default=0.0)
    a = ap.parse_args()
    rows = [json.loads(x) for x in Path(a.trials).read_text().splitlines() if x.strip()]
    tiers = a.tiers.split(",")
    cost = {}
    for kv in filter(None, a.cost.split(",")):
        k, v = kv.split("=")
        cost[k] = float(v)
    print(json.dumps(breadth_map(rows, tiers, cost, a.clear_thresh, a.wall_thresh), indent=2))
