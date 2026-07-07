"""
Aggregate contributed benchmark data (data/results/*.jsonl) into pooled
per (model, tier) stats, evidence labels, and routing recommendations.

Mirrors harness/metrics.py's math exactly (success_rate, avg_cost_per_attempt,
cost_per_success) but pools across every contributor's file instead of a
single harness_results.jsonl.

HONESTY DOCTRINE: every row in data/results/ is self-reported by whoever ran
the harness on their own machine with their own keys. A cell backed by only
one contributor is "single-source" -- a claim, not a fact. Only when >=2
DISTINCT contributors report rows for the same (model, tier) does a cell
become "corroborated". This label rides along with every number this script
prints or emits; nothing here is presented unlabeled.

Usage:
    python scripts/aggregate.py
    python scripts/aggregate.py --json
    python scripts/aggregate.py --data data/results --emit-rows merged.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cost_guard import _MODELS_RAW  # noqa: E402

# Same bar diff_report.py and generate_cheatsheet.py use: a tier only "holds"
# for routing purposes at >=2/3 measured success.
CEILING_THRESHOLD = 2 / 3

HONESTY_NOTE = (
    "all rows self-reported; corroborated means >=2 independent contributors; "
    "nothing here is vendor-verified"
)


def _finite(v: float):
    """inf is not valid JSON; represent 'no successes' as None everywhere,
    same convention as scripts/diff_report.py::_finite."""
    return None if v == float("inf") else round(v, 6)


@dataclass
class Cell:
    attempts: int = 0
    successes: int = 0
    total_cost: float = 0.0
    contributors: set = field(default_factory=set)

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def avg_cost(self) -> float:
        return self.total_cost / self.attempts if self.attempts else 0.0

    @property
    def cost_per_success(self) -> float:
        return (self.avg_cost / self.success_rate) if self.success_rate else float("inf")

    @property
    def evidence(self) -> str:
        return "corroborated" if len(self.contributors) >= 2 else "single-source"


def load_pool(data_dir: Path) -> tuple[dict[tuple[str, str], Cell], set[str], list[dict], int]:
    """Read every *.jsonl under data_dir. Returns (cells, contributor handles,
    merged raw rows minus _meta, file count). Never raises on an empty or
    missing directory -- CI and the Pages build both depend on that."""
    cells: dict[tuple[str, str], Cell] = defaultdict(Cell)
    contributors: set[str] = set()
    merged_rows: list[dict] = []
    file_count = 0

    if not data_dir.exists():
        return cells, contributors, merged_rows, file_count

    for path in sorted(data_dir.glob("*.jsonl")):
        file_count += 1
        handle = path.stem  # fallback if _meta is somehow absent
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            continue
        try:
            first = json.loads(lines[0])
        except json.JSONDecodeError:
            first = None
        data_lines = lines
        if isinstance(first, dict) and isinstance(first.get("_meta"), dict):
            handle = first["_meta"].get("contributor", handle)
            data_lines = lines[1:]

        contributors.add(handle)
        for line in data_lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or "_meta" in row:
                continue
            model, tier = row.get("model"), row.get("tier")
            if not model or not tier:
                continue
            c = cells[(model, tier)]
            c.attempts += 1
            c.contributors.add(handle)
            if row.get("pass") is True:
                c.successes += 1
            cost = row.get("actual_cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                c.total_cost += float(cost)
            merged_rows.append(row)

    return cells, contributors, merged_rows, file_count


def _price_index(model: str) -> float:
    """input_per_1M + output_per_1M, same sort key cost_guard.py uses to rank
    registry candidates cheapest-first."""
    info = _MODELS_RAW.get(model, {})
    return float(info.get("input_per_1M", 0)) + float(info.get("output_per_1M", 0))


def build_recommendations(cells: dict[tuple[str, str], Cell]) -> dict:
    tiers = sorted({tier for (_, tier) in cells})

    routing: dict[str, dict] = {}
    for tier in tiers:
        candidates = [
            (model, c) for (model, t), c in cells.items()
            if t == tier and c.success_rate >= CEILING_THRESHOLD and c.cost_per_success != float("inf")
        ]
        if not candidates:
            continue
        model, c = min(candidates, key=lambda mc: mc[1].cost_per_success)
        routing[tier] = {
            "model": model,
            "cost_per_success": _finite(c.cost_per_success),
            "evidence": c.evidence,
        }

    frontier_check: dict[str, dict] = {}
    for tier in tiers:
        tier_cells = {model: c for (model, t), c in cells.items() if t == tier}
        registry_priced = {m: c for m, c in tier_cells.items() if m in _MODELS_RAW}
        if not registry_priced:
            continue
        target, target_c = max(registry_priced.items(), key=lambda mc: _price_index(mc[0]))
        if target_c.attempts == 0:
            continue
        entry: dict = {
            "target": target,
            "target_success_rate": round(target_c.success_rate, 3),
            "target_cost_per_success": _finite(target_c.cost_per_success),
            "target_evidence": target_c.evidence,
        }
        matchers = {
            m: c for m, c in tier_cells.items()
            if m != target and c.success_rate >= target_c.success_rate and c.attempts > 0
        }
        beat = {
            m: c for m, c in matchers.items()
            if c.cost_per_success != float("inf")
            and (target_c.cost_per_success == float("inf") or c.cost_per_success < target_c.cost_per_success)
        }
        if beat:
            model, c = min(beat.items(), key=lambda mc: mc[1].cost_per_success)
            entry["verdict"] = f"replicated_by:{model}"
            entry["match"] = {
                "model": model,
                "success_rate": round(c.success_rate, 3),
                "cost_per_success": _finite(c.cost_per_success),
                "evidence": c.evidence,
            }
        else:
            entry["verdict"] = "frontier_edge"
        frontier_check[tier] = entry

    max_price = max((_price_index(m) for m in _MODELS_RAW), default=0.0)
    apprentice_candidates: list[dict] = []
    if max_price > 0:
        for model, info in _MODELS_RAW.items():
            if _price_index(model) > 0.25 * max_price:
                continue
            held_tiers = [
                t for t in ("T2", "T3", "T4", "T5")
                if (c := cells.get((model, t))) and c.attempts > 0 and c.success_rate >= CEILING_THRESHOLD
            ]
            if held_tiers:
                best_tier = max(held_tiers, key=lambda t: int(t[1]))
                c = cells[(model, best_tier)]
                apprentice_candidates.append({
                    "model": model,
                    "holds_tier": best_tier,
                    "success_rate": round(c.success_rate, 3),
                    "cost_per_success": _finite(c.cost_per_success),
                    "evidence": c.evidence,
                    "price_index": _price_index(model),
                })
        apprentice_candidates.sort(key=lambda e: e["price_index"])

    return {
        "routing": routing,
        "frontier_check": frontier_check,
        "apprentice_candidates": apprentice_candidates,
    }


def build_report(data_dir: Path) -> dict:
    cells, contributors, merged_rows, file_count = load_pool(data_dir)

    cell_list = []
    for (model, tier), c in sorted(cells.items()):
        cell_list.append({
            "model": model,
            "tier": tier,
            "attempts": c.attempts,
            "successes": c.successes,
            "success_rate": round(c.success_rate, 3),
            "avg_cost": _finite(c.avg_cost),
            "cost_per_success": _finite(c.cost_per_success),
            "contributors": len(c.contributors),
            "evidence": c.evidence,
        })

    return {
        "generated_from": {
            "files": file_count,
            "contributors": len(contributors),
            "rows": len(merged_rows),
        },
        "cells": cell_list,
        "recommendations": build_recommendations(cells),
        "honesty": HONESTY_NOTE,
        "_merged_rows": merged_rows,  # not emitted in --json; used by --emit-rows
    }


def render_text(report: dict) -> str:
    gen = report["generated_from"]
    if gen["rows"] == 0:
        return "No community data yet -- be the first: see CONTRIBUTING.md"

    L: list[str] = []
    L.append("Tier Bench — pooled community results")
    L.append("=" * 64)
    L.append(f"{gen['files']} file(s), {gen['contributors']} contributor(s), {gen['rows']} row(s)")
    L.append("")
    L.append(f"{'model':<28}{'tier':<6}{'success':<12}{'cost/success':<16}{'evidence'}")
    for cell in report["cells"]:
        sr = f"{cell['success_rate']:.0%} ({cell['successes']}/{cell['attempts']})"
        cps = "inf" if cell["cost_per_success"] is None else f"${cell['cost_per_success']:.4f}"
        L.append(f"{cell['model']:<28}{cell['tier']:<6}{sr:<12}{cps:<16}{cell['evidence']}")

    rec = report["recommendations"]
    L.append("\n" + "-" * 64)
    L.append("ROUTING (cheapest cost-per-success clearing 2/3 success, per tier)")
    if rec["routing"]:
        for tier, r in sorted(rec["routing"].items()):
            cps = "inf" if r["cost_per_success"] is None else f"${r['cost_per_success']:.4f}"
            L.append(f"  {tier}: {r['model']} — {cps}/success [{r['evidence']}]")
    else:
        L.append("  (no tier has a candidate clearing the 2/3 bar yet)")

    L.append("\nFRONTIER CHECK (highest-priced registry model with data, per tier)")
    if rec["frontier_check"]:
        for tier, e in sorted(rec["frontier_check"].items()):
            L.append(f"  {tier}: target={e['target']} [{e['target_evidence']}]")
            if e["verdict"] == "frontier_edge":
                L.append("       FRONTIER EDGE — nothing benchmarked matches at lower cost")
            else:
                m = e["match"]
                L.append(f"       {e['verdict']} [{m['evidence']}]")
    else:
        L.append("  (no registry model has pooled data yet)")

    L.append("\nAPPRENTICE CANDIDATES (<=25% of max registry price, holding T2+ at >=2/3)")
    if rec["apprentice_candidates"]:
        for a in rec["apprentice_candidates"]:
            cps = "inf" if a["cost_per_success"] is None else f"${a['cost_per_success']:.4f}"
            L.append(f"  {a['model']} — holds {a['holds_tier']} at {a['success_rate']:.0%}, {cps}/success [{a['evidence']}]")
    else:
        L.append("  (none yet)")

    L.append("\n" + report["honesty"])
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data/results", help="Directory of contributed *.jsonl files")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    ap.add_argument("--emit-rows", help="Also write all pooled raw rows (minus _meta) to this path")
    args = ap.parse_args()

    report = build_report(Path(args.data))
    merged_rows = report.pop("_merged_rows")

    if args.emit_rows:
        out = Path(args.emit_rows)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for row in merged_rows:
                f.write(json.dumps(row) + "\n")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
