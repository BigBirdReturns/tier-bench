#!/usr/bin/env python3
"""
The escalation ladder: the cheap knob (effort) before the expensive knob (access).

Two knobs, deliberately ordered:

  * EFFORT — low..max within a model (`output_config.effort`). Cheap to vary, and
    it changes capability a lot. Cascade this FIRST.
  * ACCESS — your billing cascade's quota (first -> pro -> max). Real money /
    commitment. This is NOT a rung here: it is a HUMAN gate you only reach for when
    the top effort rung walls within your current access.

So the ladder is: cheap-model + harness (the Sonnet-prepared floor), then the top
model swept across its efforts. You exhaust every effort you already have access to
before anyone pays to widen access. "Designed right, hopefully you never escalate
access" == the effort cascade clears everything before the quota runs out.

    from experiments.breadth.rungs import ladder, rung_costs, as_escalate_args
    L = ladder()                      # ['claude-haiku-4-5@harness', 'claude-fable-5@low', ... '@max']
    args = as_escalate_args(L, rung_costs())   # feeds escalate.py
"""
from __future__ import annotations

FABLE = "claude-fable-5"
BASELINE = "claude-haiku-4-5"
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

# Relative per-call cost weight of each effort (thinking + output grow with effort).
# Planning only — real per-rung cost comes from the ledger after the run.
EFFORT_WEIGHT = {"low": 1.0, "medium": 1.6, "high": 2.6, "xhigh": 4.0, "max": 6.0}


def ladder(baseline: str = BASELINE, top: str = FABLE, efforts: list[str] = EFFORTS) -> list[str]:
    """Ordered rungs, cheapest first. `<model>@harness` is the cheap floor; the rest
    is the top model's effort cascade. Access-tier escalation is not a rung."""
    return [f"{baseline}@harness"] + [f"{top}@{e}" for e in efforts]


def rung_costs(baseline: str = BASELINE, top: str = FABLE, efforts: list[str] = EFFORTS,
               baseline_usd: float = 0.03, top_low_call_usd: float = 0.30) -> dict[str, float]:
    """Rough per-call USD per rung, for planning the map before you spend. The
    baseline floor is one cheap sweep; each effort scales the top model's call cost."""
    costs = {f"{baseline}@harness": baseline_usd}
    for e in efforts:
        costs[f"{top}@{e}"] = round(top_low_call_usd * EFFORT_WEIGHT[e], 4)
    return costs


def as_escalate_args(rung_list: list[str], costs: dict[str, float]) -> list[str]:
    """Format ladder + costs into escalate.py CLI args."""
    tiers = ",".join(rung_list)
    cost = ",".join(f"{r}={costs.get(r, 0.0)}" for r in rung_list)
    return ["--tiers", tiers, "--cost", cost]


if __name__ == "__main__":
    L = ladder()
    C = rung_costs()
    print("ladder (cheapest first):")
    for r in L:
        print(f"  {r:28s} ~${C[r]:.3f}/call")
    print("\nescalate.py args:")
    print("  " + " ".join(as_escalate_args(L, C)))
