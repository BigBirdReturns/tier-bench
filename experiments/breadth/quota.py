#!/usr/bin/env python3
"""
Self-calibrating quota gauge — the meter you don't get handed, you infer.

You never see "tokens remaining this session." But you DO see when you hit the
wall. The burn between two consecutive limit-hits is one empirical sample of the
allotment. Collect a few and you have a gauge:

  * SAFE   = the smallest completed window — what you can COUNT on before the
             next wall. Plan against this.
  * LIKELY = the median completed window — what you'll TYPICALLY get.

No number from the operator required: the intervals ARE the number. Absence of
intervals is an honest answer too — with zero completed windows the quota is
UNMEASURED, and `fit_run` refuses to size quarters against a guess.

Pairs with the existing rails:
  * ledger.py  supplies the per-call token/cost rows (one burn = a slice of them)
  * limit.py   parks at 80% of a quota; this module is where that quota comes from

    # infer the gauge from a burn log, then size a run into quarters
    from experiments.breadth.quota import gauge_from_events, fit_run
    g = gauge_from_events(load("burn.jsonl"))          # {'calls': {...}, 'tokens': {...}}
    plan = fit_run(n_trials=9, per_trial_tokens=13000, quota_tokens=g['tokens']['safe'])

CLI:
    python -m experiments.breadth.quota burn.jsonl                 # print the gauge
    python -m experiments.breadth.quota burn.jsonl --fit 9 --per-trial-tokens 13000
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

# A burn-log event is one of:
#   {"type": "spend",     "calls": 1, "tokens": 12510, ...}   # accrues to the open window
#   {"type": "limit_hit", "note": "..."}                       # closes the open window
# Spend rows may carry any subset of these metrics; missing metrics count as 0.
METRICS = ("calls", "tokens")


def _metric(row: dict, key: str) -> float:
    if key == "calls":
        # an explicit calls count, else one row == one call
        return float(row.get("calls", 1) or 0)
    return float(row.get(key, 0) or 0)


def filter_by_account(events: list[dict], account: str | None) -> list[dict]:
    """Keep only events for one account tier (plus `limit_hit` markers, which are
    account-agnostic wall attestations). A Plus wall and a Max20x wall are
    different meters — pooling their windows makes SAFE meaningless, so gauge
    per-account. `account=None` keeps everything (the default, unfiltered gauge —
    back-compat). Under a specific account ONLY rows explicitly tagged with it
    count: untagged legacy rows predate tagging (unknown lineage) and are excluded
    rather than silently attributed, so a filtered gauge never inflates on a guess."""
    if not account:
        return events
    return [ev for ev in events
            if ev.get("type") == "limit_hit" or ev.get("account") == account]


def windows_from_events(events: list[dict]) -> dict:
    """Split a flat burn log into completed windows (each ended by a limit_hit)
    plus the still-open current window. A window's burn is the sum of its spend
    rows per metric."""
    completed: list[dict] = []
    cur = {k: 0.0 for k in METRICS}
    cur["spends"] = 0
    for ev in events:
        etype = ev.get("type", "spend")
        if etype == "limit_hit":
            if cur["spends"] > 0:            # never emit an empty window (double-hit)
                completed.append({k: cur[k] for k in METRICS})
            cur = {k: 0.0 for k in METRICS}
            cur["spends"] = 0
        else:
            cur["spends"] += 1
            for k in METRICS:
                cur[k] += _metric(ev, k)
    current = {k: cur[k] for k in METRICS}
    current["spends"] = cur["spends"]
    return {"completed": completed, "current": current}


def estimate_metric(completed: list[dict], key: str, warn_frac: float = 0.8) -> dict:
    """Gauge one metric from the completed windows. `known` is False until at
    least one window has closed — absence of a wall is not a quota of infinity."""
    burns = [w[key] for w in completed if key in w]
    if not burns:
        return {"known": False, "samples": 0,
                "note": f"no completed limit-window yet — {key} quota UNMEASURED"}
    safe = min(burns)
    return {
        "known": True,
        "samples": len(burns),
        "safe": round(safe, 3),                       # count on this before the wall
        "likely": round(statistics.median(burns), 3),  # typically get this
        "max_seen": round(max(burns), 3),
        "checkpoint_at": round(safe * warn_frac, 3),   # act here, not at the wall
        "note": ("single sample — treat 'safe' as provisional until a 2nd window closes"
                 if len(burns) == 1 else f"{len(burns)} windows; safe = smallest observed"),
    }


def gauge_from_events(events: list[dict], warn_frac: float = 0.8) -> dict:
    """The full gauge: per-metric estimate plus the open window's burn-so-far,
    so a live run can see how close it is to its own inferred wall."""
    w = windows_from_events(events)
    out = {"warn_frac": warn_frac,
           "current_window": w["current"],
           "completed_windows": len(w["completed"])}
    for k in METRICS:
        out[k] = estimate_metric(w["completed"], k, warn_frac)
        est = out[k]
        if est.get("known"):
            burned = w["current"].get(k, 0.0)
            est["current_burned"] = round(burned, 3)
            est["remaining_to_safe"] = round(max(est["safe"] - burned, 0.0), 3)
            est["approaching"] = burned >= est["checkpoint_at"]
    return out


def fit_run(n_trials: int, per_trial_tokens: float | None = None,
            quota_tokens: float | None = None, per_trial_calls: float = 1.0,
            quota_calls: float | None = None, quarters: int = 4,
            warn_frac: float = 0.8) -> dict:
    """Size a run against an inferred quota, split into `quarters` checkpoints.

    Whichever metric binds first (tokens or calls) sets windows_needed — you hit
    the wall on the tighter one. UNMEASURED quota is not sized against a guess."""
    if quota_tokens is None and quota_calls is None:
        return {"sizable": False,
                "reason": "quota UNMEASURED — no completed limit-window to gauge against; "
                          "run one block, hit the wall once, then this can size quarters"}

    def _need(per_trial, quota):
        if per_trial is None or quota is None or quota <= 0:
            return None
        usable = quota * warn_frac                    # never plan into the top 20%
        per_window = math.floor(usable / per_trial) if per_trial > 0 else n_trials
        per_window = max(per_window, 1)
        windows = math.ceil(n_trials / per_window)
        return {"per_trial": per_trial, "quota": quota, "usable_at_warn": round(usable, 3),
                "trials_per_window": per_window, "windows_needed": windows}

    tok = _need(per_trial_tokens, quota_tokens)
    cal = _need(per_trial_calls, quota_calls)
    binders = {k: v for k, v in (("tokens", tok), ("calls", cal)) if v}
    if not binders:
        return {"sizable": False, "reason": "need per-trial + quota for at least one metric"}
    # the binding metric is the one demanding the most windows (tightest wall)
    binding = max(binders, key=lambda k: binders[k]["windows_needed"])
    per_window = binders[binding]["trials_per_window"]
    windows_needed = binders[binding]["windows_needed"]

    # quarter the work actually scheduled in this window: the whole run if it
    # fits, else one window's worth (the checkpoint cadence across the wall)
    span = n_trials if windows_needed <= 1 else per_window
    per_quarter = max(math.ceil(span / quarters), 1)
    checkpoints = []
    done = 0
    for q in range(1, quarters + 1):
        take = min(per_quarter, span - done)
        if take <= 0:
            break
        done += take
        checkpoints.append({"quarter": q, "trials": take, "cumulative": done,
                            "action": "seal + ledger-log + gauge check, then continue"})
    return {
        "sizable": True,
        "n_trials": n_trials,
        "binding_metric": binding,
        "metrics": binders,
        "trials_per_window": per_window,
        "windows_needed": windows_needed,
        "fits_one_window": windows_needed <= 1,
        "quarter_plan": checkpoints,
        "note": (f"{n_trials} trials fit in one quota window (~{per_window} headroom); "
                 f"checkpoint every ~{per_quarter} trials"
                 if windows_needed <= 1 else
                 f"{n_trials} trials need {windows_needed} quota windows of ~{per_window} "
                 f"each — checkpoint at every quarter and expect {windows_needed-1} wall(s)"),
    }


def per_trial_from_ledger(rows: list[dict], metric: str = "tokens") -> float | None:
    """Mean per-call burn from ledger rows — the per_trial input for fit_run.
    tokens = input+output+cache_write (cache reads are ~0.1x; excluded as 'new')."""
    if not rows:
        return None
    if metric == "calls":
        return 1.0
    total = 0.0
    for r in rows:
        total += (float(r.get("input_tokens", 0) or 0)
                  + float(r.get("output_tokens", 0) or 0)
                  + float(r.get("cache_write_tokens", 0) or 0))
    return round(total / len(rows), 3)


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Self-calibrating quota gauge + quarter planner.")
    ap.add_argument("burnlog", help="jsonl burn log: spend rows + limit_hit markers")
    ap.add_argument("--account", default=None,
                    help="gauge only this account tier (e.g. max20x, plus). A Plus wall "
                         "and a Max20x wall are different meters; untagged legacy rows are "
                         "excluded. Omit to gauge all rows pooled (the original behavior).")
    ap.add_argument("--warn-frac", type=float, default=0.8)
    ap.add_argument("--fit", type=int, metavar="N_TRIALS", default=None)
    ap.add_argument("--per-trial-tokens", type=float, default=None)
    ap.add_argument("--per-trial-calls", type=float, default=1.0)
    ap.add_argument("--quarters", type=int, default=4)
    a = ap.parse_args()
    events = [json.loads(x) for x in Path(a.burnlog).read_text(encoding="utf-8").splitlines() if x.strip()]
    events = filter_by_account(events, a.account)
    g = gauge_from_events(events, a.warn_frac)
    if a.account:
        g["account"] = a.account
    print(json.dumps(g, indent=2))
    if a.fit is not None:
        qt = g["tokens"].get("safe") if g["tokens"].get("known") else None
        qc = g["calls"].get("safe") if g["calls"].get("known") else None
        plan = fit_run(a.fit, per_trial_tokens=a.per_trial_tokens, quota_tokens=qt,
                       per_trial_calls=a.per_trial_calls, quota_calls=qc, quarters=a.quarters,
                       warn_frac=a.warn_frac)
        print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
