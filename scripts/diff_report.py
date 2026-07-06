"""Frontier diff report.

Answers two questions from measured benchmark data, per tier:

  1. CAPABILITY DIFF — what does the target (frontier) model actually give
     you over everything else that was benchmarked?
  2. REPLICATION — which cheaper model or composite matches the target's
     success rate, and at what fraction of its cost-per-success?

The report is registry-driven: the target defaults to roles.driver in
models.json but any model name works (--target), so the same report keeps
working as models come and go. It only speaks about what was measured —
tiers with no deterministic tasks are called out as unmeasured, never guessed.

Usage:
    python scripts/diff_report.py                        # target = roles.driver
    python scripts/diff_report.py --target some-model
    python scripts/diff_report.py --json                 # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cost_guard import ROLES, Tier, _MODELS_RAW  # noqa: E402
from harness.metrics import compute  # noqa: E402

# A tier "holds" for a model when it passes at least this share of attempts.
CEILING_THRESHOLD = 2 / 3


def _fmt_cps(v) -> str:
    return "inf" if v is None else f"${v:.4f}"


def _finite(v: float):
    """inf is not valid JSON; represent 'no successes' as None everywhere."""
    return None if v == float("inf") else round(v, 6)


def build_diff(results_path: Path, target: str) -> dict:
    stats = compute(results_path)

    tiers = sorted({tier for (_, tier) in stats})
    report: dict = {"target": target, "tiers": [], "measured_ceiling": None}

    for tier in tiers:
        t = stats.get((target, tier))
        competitors = {
            m: s for (m, tr), s in stats.items() if tr == tier and m != target and s.attempts > 0
        }

        entry: dict = {"tier": tier}
        if t is None or t.attempts == 0:
            entry["verdict"] = "no_target_data"
            entry["note"] = f"{target} has no rows at {tier}; run the benchmark first."
            report["tiers"].append(entry)
            continue

        entry["target"] = {
            "attempts": t.attempts,
            "success_rate": round(t.success_rate, 3),
            "cost_per_success": _finite(t.cost_per_success),
        }

        if t.success_rate == 0:
            entry["verdict"] = "target_fails_tier"
            entry["note"] = "Nothing to replicate: the target itself fails here."
            report["tiers"].append(entry)
            continue

        # Replication check: competitors that match-or-beat the target's
        # measured success rate, ranked by cost-per-success.
        matchers = {
            m: s for m, s in competitors.items() if s.success_rate >= t.success_rate
        }
        if matchers:
            best = min(matchers.items(), key=lambda kv: kv[1].cost_per_success)
            name, s = best
            ratio = (
                t.cost_per_success / s.cost_per_success
                if s.cost_per_success not in (0, float("inf"))
                else float("inf")
            )
            entry["best_match"] = {
                "model": name,
                "success_rate": round(s.success_rate, 3),
                "cost_per_success": _finite(s.cost_per_success),
                "cost_ratio": None if ratio == float("inf") else round(ratio, 1),
            }
            if s.cost_per_success <= t.cost_per_success:
                entry["verdict"] = "replicated"
            else:
                entry["verdict"] = "matched_not_cheaper"
        else:
            entry["verdict"] = "frontier_edge"
            entry["note"] = (
                "No benchmarked model or composite matches the target's success "
                "rate at this tier. This is the measured part of what you pay for."
            )
        report["tiers"].append(entry)

    # Measured ceiling vs the registry hypothesis.
    held = [
        e["tier"] for e in report["tiers"]
        if e.get("target") and e["target"]["success_rate"] >= CEILING_THRESHOLD
    ]
    report["measured_ceiling"] = max(held) if held else None
    report["hypothesis_ceiling"] = _MODELS_RAW.get(target, {}).get("tier_ceiling")
    benchmarked = {t.name for t in Tier if any(e["tier"] == t.name for e in report["tiers"])}
    unmeasured = [t.name for t in Tier if t.name not in benchmarked]
    report["unmeasured_tiers"] = unmeasured
    return report


VERDICT_LINES = {
    "replicated": "REPLICATED — {model} matches at {ratio}x lower cost-per-success",
    "matched_not_cheaper": "MATCHED by {model}, but not more cheaply",
    "frontier_edge": "FRONTIER EDGE — nothing benchmarked matches; this is what you pay for",
    "target_fails_tier": "TARGET FAILS this tier",
    "no_target_data": "no data for target at this tier",
}


def render_text(report: dict) -> str:
    L: list[str] = []
    target = report["target"]
    L.append(f"Frontier diff — target: {target}")
    L.append("=" * 64)
    for e in report["tiers"]:
        L.append(f"\n{e['tier']}")
        t = e.get("target")
        if t:
            L.append(
                f"  target : {t['success_rate']:.0%} success, "
                f"{_fmt_cps(t['cost_per_success'])}/success ({t['attempts']} attempts)"
            )
        m = e.get("best_match")
        if m:
            L.append(
                f"  match  : {m['model']} — {m['success_rate']:.0%} success, "
                f"{_fmt_cps(m['cost_per_success'])}/success"
            )
        verdict = e.get("verdict", "")
        line = VERDICT_LINES.get(verdict, verdict)
        if m:
            line = line.format(model=m["model"], ratio=m.get("cost_ratio") or "?")
        L.append(f"  verdict: {line}")
        if e.get("note"):
            L.append(f"           {e['note']}")

    L.append("\n" + "-" * 64)
    L.append(f"Measured ceiling : {report['measured_ceiling'] or 'none held at >=67%'}")
    L.append(f"Registry claim   : {report['hypothesis_ceiling'] or 'not registered'}")
    if report["unmeasured_tiers"]:
        L.append(
            f"Unmeasured tiers : {', '.join(report['unmeasured_tiers'])} — no deterministic "
            "tasks ran there. Capability above the ruler is a claim, not a measurement."
        )
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="harness_results.jsonl")
    ap.add_argument("--target", default=ROLES.get("driver"),
                    help="Model to diff against the field (default: roles.driver from models.json)")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()

    if not args.target:
        print("No --target given and no roles.driver in models.json.")
        return 2
    results = Path(args.results)
    if not results.exists():
        print(f"No results at {results}. Run: python orchestrator.py --benchmark all")
        return 2

    report = build_diff(results, args.target)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
