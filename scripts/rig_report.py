"""Rig report: what can THIS machine already do, and what's the next rung?

Probes local hardware (RAM, cores, GPUs / unified memory), maps it against
the model registry, and prints:

  1. what local models fit on this rig right now,
  2. which task tiers that covers — i.e. what you already get for $0,
  3. commodity vs frontier: which tiers cheap/local options handle and which
     genuinely need a frontier model (measured when harness_results.jsonl
     exists; labeled HYPOTHESIS when it doesn't),
  4. upgrade paths: the next memory rungs, what each unlocks, and the
     no-hardware alternative (cheap API models + composites).

Everything model-specific comes from models.json. Simulate a rig you're
considering with --ram-gb / --vram-gb / --unified.

Usage:
    python scripts/rig_report.py
    python scripts/rig_report.py --vram-gb 24            # "what if" a 24 GB GPU
    python scripts/rig_report.py --emit-config           # paste-ready registry fragment
    python scripts/rig_report.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cost_guard import _MODELS_RAW, ROLES, Tier  # noqa: E402
from harness.metrics import compute  # noqa: E402
from harness.rig import (  # noqa: E402
    Rig, detect_rig, fits, gb_needed, max_params_b, next_rungs,
)

LOCAL_PROVIDERS = {"ollama", "openai-compat"}
CEILING_THRESHOLD = 2 / 3

# What each tier means in working terms — quality in plain language.
TIER_QUALITY = {
    "T0": "formatting, lint fixes, renames — zero-logic clerical edits",
    "T1": "small functions and unit tests written from a clear spec",
    "T2": "bug fixes, API wiring, small multi-file patches",
    "T3": "security fixes, gnarly refactors, cross-module debugging",
    "T4": "planning and decomposition of larger jobs (validated as plans)",
    "T5": "architectural judgment — not benchmarked, human-reviewed",
}

TIER_ORDER = [t.name for t in Tier]


def local_models() -> dict[str, dict]:
    return {
        name: info for name, info in _MODELS_RAW.items()
        if info.get("provider") in LOCAL_PROVIDERS and info.get("params_B")
    }


def api_models() -> dict[str, dict]:
    return {
        name: info for name, info in _MODELS_RAW.items()
        if info.get("provider") not in LOCAL_PROVIDERS
    }


def measured_ceilings(results_path: Path) -> dict[str, str]:
    """model -> highest tier held at >= CEILING_THRESHOLD success, from results."""
    if not results_path.exists():
        return {}
    stats = compute(results_path)
    held: dict[str, list[str]] = {}
    for (model, tier), s in stats.items():
        if s.attempts > 0 and s.success_rate >= CEILING_THRESHOLD:
            held.setdefault(model, []).append(tier)
    return {m: max(tiers) for m, tiers in held.items()}


def ceiling_of(name: str, info: dict, measured: dict[str, str]) -> tuple[str, bool]:
    """(tier, is_measured). Falls back to the registry hypothesis."""
    if name in measured:
        return measured[name], True
    return str(info.get("tier_ceiling", "T0")), False


def tier_max(tiers: list[str]) -> str | None:
    ranked = [t for t in TIER_ORDER if t in tiers]
    return ranked[-1] if ranked else None


def build_report(rig: Rig, results_path: Path) -> dict:
    measured = measured_ceilings(results_path)
    have_results = bool(measured)

    # 1. What fits now
    runnable, too_big = [], []
    for name, info in sorted(local_models().items(), key=lambda kv: kv[1]["params_B"]):
        ceiling, is_measured = ceiling_of(name, info, measured)
        entry = {
            "model": name,
            "params_B": info["params_B"],
            "gb_needed": gb_needed(info["params_B"]),
            "tier_ceiling": ceiling,
            "ceiling_measured": is_measured,
        }
        (runnable if fits(info["params_B"], rig) else too_big).append(entry)

    local_ceiling = tier_max([e["tier_ceiling"] for e in runnable])

    # 2. Commodity vs frontier, per tier: the cheapest thing that holds the
    # tier. Local $0 beats cheap API beats frontier. "Cheap" is relative to
    # the priciest registered model (<= 25% of its price index), so the
    # threshold keeps meaning something as absolute prices drift over years.
    max_price = max(
        i.get("input_per_1M", 0) + i.get("output_per_1M", 0)
        for i in _MODELS_RAW.values()
    ) or 1.0
    tiers_out = []
    for tier in TIER_ORDER:
        if tier in ("T4", "T5"):
            tiers_out.append({
                "tier": tier, "quality": TIER_QUALITY[tier],
                "verdict": "unmeasured",
                "note": "no deterministic tasks — capability here is a claim, not a measurement",
            })
            continue
        holders = []
        for name, info in _MODELS_RAW.items():
            ceiling, is_measured = ceiling_of(name, info, measured)
            if TIER_ORDER.index(ceiling) >= TIER_ORDER.index(tier):
                is_local = info.get("provider") in LOCAL_PROVIDERS
                price = info.get("input_per_1M", 0) + info.get("output_per_1M", 0)
                holders.append({
                    "model": name, "local": is_local, "price_index": price,
                    "measured": is_measured,
                    "fits_this_rig": is_local and bool(info.get("params_B"))
                    and fits(info["params_B"], rig),
                })
        local_here = [h for h in holders if h["fits_this_rig"]]
        cheap_api = sorted((h for h in holders if not h["local"]),
                           key=lambda h: h["price_index"])
        entry = {"tier": tier, "quality": TIER_QUALITY[tier]}
        chosen = None
        if local_here:
            entry["verdict"] = "commodity_local"
            chosen = local_here[0]
            entry["note"] = "your rig already does this for $0"
        elif cheap_api and cheap_api[0]["price_index"] <= 0.25 * max_price:
            entry["verdict"] = "commodity_api"
            chosen = cheap_api[0]
            entry["note"] = "pennies via a small API model — no frontier needed"
        else:
            entry["verdict"] = "frontier"
            chosen = cheap_api[0] if cheap_api else None
            entry["note"] = "only frontier-priced models hold this tier"
        if chosen:
            entry["cheapest"] = chosen["model"]
            # The evidence tag speaks about the CHOSEN model, not the tier —
            # "something here was measured" must never dress up a hypothesis.
            entry["evidence"] = ("measured" if chosen["measured"]
                                 else "hypothesis — run the benchmark")
        tiers_out.append(entry)

    # 3. Upgrade paths. Each rung reports its MARGINAL unlocks — what it adds
    # over the rung before it — so the ladder reads as a path, not a loop.
    upgrades = []
    prev_usable = rig.usable_gb
    ceilings_so_far = [e["tier_ceiling"] for e in runnable]
    for usable, label, how in next_rungs(rig, count=3):
        unlocked = [
            {"model": n, "params_B": i["params_B"],
             "tier_ceiling": ceiling_of(n, i, measured)[0]}
            for n, i in sorted(local_models().items(), key=lambda kv: kv[1]["params_B"])
            if gb_needed(i["params_B"]) <= usable and gb_needed(i["params_B"]) > prev_usable
        ]
        ceilings_so_far += [u["tier_ceiling"] for u in unlocked]
        upgrades.append({
            "rung": label, "how": how, "usable_gb": usable,
            "unlocks": unlocked, "local_ceiling_after": tier_max(ceilings_so_far),
        })
        prev_usable = usable

    return {
        "rig": {
            "ram_gb": rig.ram_gb, "cpu_cores": rig.cpu_cores, "gpus": rig.gpus,
            "resource_nodes": rig.resource_nodes,
            "aggregate_vram_gb": rig.aggregate_vram_gb,
            "capacity_pooling": rig.capacity_pooling,
            "unified_memory": rig.unified_memory, "usable_gb": rig.usable_gb,
            "class": rig.compute_class, "max_params_B_q4": max_params_b(rig.usable_gb),
        },
        "runnable_now": runnable,
        "too_big": [e["model"] for e in too_big],
        "local_ceiling": local_ceiling,
        "tiers": tiers_out,
        "upgrade_paths": upgrades,
        "driver": ROLES.get("driver"),
        "evidence_base": "measured" if have_results else "registry hypotheses",
    }


def emit_config(report: dict) -> str:
    """Paste-ready registry fragment wiring this rig in: pull commands for the
    best runnable local models, and a driver_repair composite that uses the
    best local model as hands under the configured driver."""
    runnable = report["runnable_now"]
    if not runnable:
        return "# Nothing local fits this rig yet — see upgrade paths, or use API hands."
    best = max(runnable, key=lambda e: (TIER_ORDER.index(e["tier_ceiling"]), e["params_B"]))
    driver = report.get("driver") or "<your-driver-model>"
    lines = ["# 1. Pull the local models that fit this rig:"]
    for e in runnable:
        lines.append(f"#      ollama pull {e['model']}")
    lines.append("# 2. Merge into the 'composites' section of models.json:")
    frag = {
        f"driver:local-{best['model']}": {
            "strategy": "driver_repair",
            "driver": driver,
            "members": [best["model"]],
            "max_repairs": 1,
            "tier_ceiling": best["tier_ceiling"],
        }
    }
    lines.append(json.dumps(frag, indent=2))
    lines.append("# 3. Benchmark it:  python orchestrator.py --benchmark all")
    return "\n".join(lines)


def render_text(report: dict) -> str:
    L: list[str] = []
    r = report["rig"]
    L.append("Rig report")
    L.append("=" * 64)
    gpu_txt = ", ".join(f"{g['name']} ({g['vram_gb']} GB)" for g in r["gpus"]) or "none detected"
    L.append(f"class      : {r['class']}")
    L.append(f"memory     : RAM {r['ram_gb']} GB | GPU {gpu_txt}"
             + (" | unified" if r["unified_memory"] else ""))
    if len(r["resource_nodes"]) > 1:
        L.append(
            f"scheduling : {len(r['resource_nodes'])} independent devices; "
            f"{r['aggregate_vram_gb']} GB aggregate inventory is not pooled or qualified"
        )
    boundary = "largest independent device" if r["gpus"] else "available memory"
    L.append(f"usable     : ~{r['usable_gb']} GB on the {boundary} for weights+KV  "
             f"(≈ {r['max_params_B_q4']}B params max at Q4)")

    L.append("\nRunnable locally right now ($0/token):")
    if report["runnable_now"]:
        for e in report["runnable_now"]:
            tag = "measured" if e["ceiling_measured"] else "hypothesis"
            L.append(f"  - {e['model']:<20} {e['params_B']:>4}B  needs ~{e['gb_needed']} GB  "
                     f"→ ceiling {e['tier_ceiling']} ({tag})")
        L.append(f"  local ceiling: {report['local_ceiling']} — "
                 f"{TIER_QUALITY.get(report['local_ceiling'], '')}")
    else:
        L.append("  (none fit — see upgrade paths below, or use API hands)")
    if report["too_big"]:
        L.append(f"  too big for this rig: {', '.join(report['too_big'])}")

    L.append("\nCommodity vs frontier, per tier:")
    for t in report["tiers"]:
        v = t["verdict"]
        marker = {"commodity_local": "🟢 commodity (local)",
                  "commodity_api": "🟡 commodity (cheap API)",
                  "frontier": "🔴 frontier",
                  "unmeasured": "⚪ unmeasured"}.get(v, v)
        L.append(f"  {t['tier']}: {marker} — {t['quality']}")
        cheapest = t.get("cheapest")
        note = t.get("note", "")
        L.append(f"       {('cheapest: ' + cheapest + ' — ') if cheapest else ''}{note}")
        if t.get("evidence") and v != "unmeasured":
            L.append(f"       evidence: {t['evidence']}")

    L.append("\nUpgrade paths:")
    for u in report["upgrade_paths"]:
        L.append(f"  → {u['rung']} ({u['how']}; ~{u['usable_gb']} GB usable)")
        if u["unlocks"]:
            for m in u["unlocks"]:
                L.append(f"      unlocks {m['model']} ({m['params_B']}B, ceiling {m['tier_ceiling']})")
            L.append(f"      local ceiling after: {u['local_ceiling_after']}")
        else:
            L.append("      unlocks nothing new in the current registry — add bigger local models first")
    L.append("  → no-hardware path: cheap API models + composites already cover the "
             "commodity tiers above; spend frontier money on judgment (the driver), not typing.")

    L.append("\n" + "-" * 64)
    L.append(f"Evidence base: {report['evidence_base']}. Hypotheses become measurements "
             "with: python orchestrator.py --benchmark all")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="harness_results.jsonl")
    ap.add_argument("--ram-gb", type=float, help="Simulate system RAM instead of probing")
    ap.add_argument("--vram-gb", type=float, help="Simulate aggregate GPU inventory VRAM instead of probing")
    ap.add_argument("--gpus", type=int, default=None, help="Simulated GPU count (with --vram-gb)")
    ap.add_argument("--unified", action="store_true", help="Simulate unified memory (Apple silicon class)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit-config", action="store_true",
                    help="Print a paste-ready models.json fragment for this rig")
    args = ap.parse_args()

    if args.ram_gb or args.vram_gb:
        n = args.gpus or (1 if args.vram_gb else 0)
        gpus = (
            [
                {
                    "uuid": f"simulated:{index}",
                    "name": "simulated",
                    "vram_gb": round(args.vram_gb / n, 1),
                }
                for index in range(n)
            ]
            if args.vram_gb
            else []
        )
        rig = Rig(ram_gb=args.ram_gb, cpu_cores=None, gpus=gpus, unified_memory=args.unified)
    else:
        rig = detect_rig()

    report = build_report(rig, Path(args.results))
    if args.emit_config:
        print(emit_config(report))
    elif args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
