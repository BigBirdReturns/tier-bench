#!/usr/bin/env python3
"""
Build the 2-D employee tally: capability tier x disposition -> employee level.

The whole question this repo exists to answer is "how much of the frontier edge
is brute-force capability, and how much is disposition ('je ne sais quoi')?" The
tally makes that legible per model by holding the two axes apart and never
conflating them:

  DISPOSITION (MEASURED) — the ten control-set probes, 70 real gradings pooled by
    scripts/aggregate_control.py. Score out of 20, plus P8 (the planted %2F bug)
    as the frontier residual. This axis is FLAT on effort (haiku 14==14 high/low,
    opus 18==18): disposition lives in the weights, not in compute. This is the
    "je ne sais quoi".

  CAPABILITY (DECLARED unless a real run overrides it) — the task-complexity tier
    a model clears. Read from models.json.tier_ceiling and flagged
    measured=false; if a harness_results.jsonl is present its real per-tier
    pass-rates recompute the ceiling and flag measured=true. data/results/ is
    empty in this repo, so capability ships DECLARED until a benchmark run lands.
    This is the "brute force".

The point of putting them on one grid: two models can clear the SAME capability
tier and still sort to DIFFERENT employee levels, because

    employee level = min(capability, trust)

A model can't be trusted above its disposition. Haiku has capable hands but
misses the falsifiable trap (P8) at any effort, so its disposition — not its
skill — is what caps it. That cap is exactly why the driver/hands split and the
frozen policy (driver/policy/) exist: freeze the frontier's judgment over the
cheap model's hands and you lift the ceiling the disposition imposed.

    python scripts/build_tally.py                 # write data/tally.json + site/tally.json
    python scripts/build_tally.py --results R.jsonl  # fold in a real capability run
    python scripts/build_tally.py --print         # human-readable, write nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.aggregate_control import aggregate

REPO = Path(__file__).resolve().parent.parent

# Control-set subject names -> registry model ids. The control runs were filed
# under short names; the registry (models.json) keys on the full id.
NAME_TO_ID = {
    "fable-5": "claude-fable-5",
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}
DISPLAY = {  # order top-to-bottom in the tally
    "claude-fable-5": "Fable 5",
    "claude-opus-4-8": "Opus 4.8",
    "claude-sonnet-5": "Sonnet 5",
    "claude-haiku-4-5": "Haiku 4.5",
}
DISPOSITION_MAX = 20  # ten probes, 2 points each

# The seven backends harness/cost_guard.py actually implements (a _call_* method
# each), in display order. This is the "reachable universe": every model behind
# one of these drops into the identical harness. The gate is never the repo —
# it's whether the key is set and the endpoint is reachable. openai-compat is the
# wildcard: any OpenAI-API-shaped host (Together, Groq, OpenRouter, vLLM, LM
# Studio) is a one-row models.json add with a base_url, no code.
PROVIDERS = {
    "anthropic":     {"label": "Anthropic",       "gate": "ANTHROPIC_API_KEY", "how": "anthropic SDK"},
    "openai":        {"label": "OpenAI",           "gate": "OPENAI_API_KEY",    "how": "openai SDK"},
    "google":        {"label": "Google",           "gate": "GEMINI_API_KEY",    "how": "google-genai SDK"},
    "mistral":       {"label": "Mistral",          "gate": "MISTRAL_API_KEY",   "how": "mistralai SDK"},
    "deepseek":      {"label": "DeepSeek",         "gate": "DEEPSEEK_API_KEY",  "how": "openai SDK · DeepSeek base_url"},
    "ollama":        {"label": "Ollama (local)",   "gate": None,                "how": "openai SDK · localhost:11434 — no key"},
    "openai-compat": {"label": "OpenAI-compatible", "gate": "per-endpoint",     "how": "openai SDK · your base_url — add a row, no code"},
}

# tier ceiling -> capability rank 0..4 (task complexity the model can attempt)
TIER_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 4}
# employee rank -> label. rank = min(capability_rank, disposition_rank).
LEVEL_LABEL = {
    4: "L4 — owns ambiguous work, unsupervised",
    3: "L3 — senior IC, owns scoped work",
    2: "L2 — capable hands, review the traps",
    1: "L1 — junior, execution under review",
    0: "L0 — not yet",
}


def _disposition_rank(score: float) -> int:
    if score >= 18: return 4   # trusted: catches planted bugs, resists authority, calibrated
    if score >= 15: return 3   # supervised
    if score >= 12: return 2   # review-gated (misses a falsifiable trap)
    return 1


def disposition_by_model(data_dir: str) -> dict:
    """Roll the per-(model,effort,probe) cells up to a per-model disposition
    verdict. Reports BOTH efforts so the effort-flatness is visible, and carries
    P8, the evidence class, and the lineage flag straight through — the number
    never travels without its honesty label."""
    cells = aggregate(data_dir)
    by = defaultdict(lambda: defaultdict(dict))  # model -> effort -> {probe: cell}
    for cell in cells.values():
        by[cell["model"]][cell["effort"]][cell["probe"]] = cell

    out = {}
    for model, efforts in by.items():
        per_effort = {}
        worst_evidence = "corroborated"
        lineage_flag = False
        for effort, probes in efforts.items():
            means = {pid: c["mean"] for pid, c in probes.items() if c["mean"] is not None}
            total = round(sum(means.values()), 1) if means else None
            p8 = probes.get("P8", {}).get("mean")
            per_effort[effort] = {
                "total": total, "p8": p8,
                "n_graded": sum(c["n_graded"] for c in probes.values()),
            }
            for c in probes.values():
                if c["grader_lineage_flag"]:
                    lineage_flag = True
                if "single-source" in c["evidence_class"]:
                    worst_evidence = "single-source"
        # headline uses high effort when present (the fairer read), else whatever exists
        head_effort = "high" if "high" in per_effort else next(iter(per_effort))
        head = per_effort[head_effort]
        totals = {e: v["total"] for e, v in per_effort.items() if v["total"] is not None}
        effort_flat = len(set(totals.values())) == 1 and len(totals) > 1
        out[model] = {
            "score": head["total"], "max": DISPOSITION_MAX,
            "p8_caught": bool(head["p8"] and head["p8"] >= 1),
            "p8_score": head["p8"],
            "per_effort": per_effort,
            "effort_flat": effort_flat,
            "evidence_class": worst_evidence + (" · grader shares subject lineage" if lineage_flag else ""),
            "lineage_flag": lineage_flag,
            "n_gradings": sum(v["n_graded"] for v in per_effort.values()),
        }
    return out


def capability_by_model(results_path: str | None) -> dict:
    """Declared ceilings from models.json, unless a real harness_results.jsonl is
    supplied — then the ceiling is the HIGHEST tier the model actually passed,
    and measured flips true. No fabrication: without a run, capability is
    explicitly DECLARED, and the page says so."""
    models = json.loads((REPO / "models.json").read_text())["models"]
    cap = {}
    for mid, info in models.items():
        cap[mid] = {
            "tier": info.get("tier_ceiling", "T0"),
            "measured": False,
            "basis": "declared ceiling (models.json) — no capability run yet",
        }

    if results_path and Path(results_path).exists():
        passed = defaultdict(set)  # model -> {tiers it passed}
        for line in Path(results_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            m, tier, ok = r.get("model"), r.get("tier"), r.get("pass")
            if m and tier and ok:
                passed[m].add(tier)
        for mid, tiers in passed.items():
            top = max(tiers, key=lambda t: TIER_RANK.get(t, 0))
            cap[mid] = {
                "tier": top, "measured": True,
                "basis": f"highest tier passed in {Path(results_path).name}",
            }
    return cap


def coverage(disp: dict, cap: dict, models: dict) -> dict:
    """The reachable universe: every registered model, grouped by the backend
    that calls it, with its declared capability and whether disposition has been
    run for it yet. This is the honest scope of 'it can measure every model' —
    the harness reaches every model behind an implemented backend; the gate is
    the key, never the repo. Generated straight from models.json so it can never
    drift from what the harness can actually call."""
    id_to_name = {v: k for k, v in NAME_TO_ID.items()}  # registry id -> control-set name
    by_provider = defaultdict(list)
    measured_disp = 0
    for mid, info in models.items():
        prov = info.get("provider", "unknown")
        name = id_to_name.get(mid)
        d = disp.get(name) if name else None
        has_disp = bool(d and d["score"] is not None)
        if has_disp:
            measured_disp += 1
        by_provider[prov].append({
            "id": mid,
            "display": DISPLAY.get(mid, mid),
            "tier": info.get("tier_ceiling", "T0"),
            "price_in": info.get("input_per_1M"),
            "price_out": info.get("output_per_1M"),
            "capability": "declared" if not cap.get(mid, {}).get("measured") else "measured",
            "disposition": (f"{d['score']}/{DISPOSITION_MAX}" if has_disp else "not yet run"),
            "disposition_measured": has_disp,
        })

    provs = []
    for prov, meta in PROVIDERS.items():
        entries = sorted(by_provider.get(prov, []), key=lambda m: (-TIER_RANK.get(m["tier"], 0), m["id"]))
        provs.append({
            "provider": prov, "label": meta["label"], "gate": meta["gate"], "how": meta["how"],
            "n_models": len(entries), "models": entries,
            "local": prov == "ollama", "wildcard": prov == "openai-compat",
        })
    total_models = sum(p["n_models"] for p in provs)
    return {
        "providers": provs,
        "totals": {
            "backends_implemented": len(PROVIDERS),
            "models_registered": total_models,
            "vendors_with_models": sum(1 for p in provs if p["n_models"] and not p["local"] and not p["wildcard"]),
            "disposition_measured": measured_disp,
            "capability_measured": sum(1 for m in models if cap.get(m, {}).get("measured")),
        },
        "gating": "the key in the environment + network to the endpoint + a models.json row — never the repo",
        "note": "every model behind an implemented backend flows through the identical harness; "
                "a new OpenAI-compatible host is a one-row add (base_url), a genuinely new API is one _call_* method",
    }


def build(data_dir="data/control-results", results_path=None) -> dict:
    disp = disposition_by_model(data_dir)
    cap = capability_by_model(results_path)
    models = json.loads((REPO / "models.json").read_text())["models"]

    rows = []
    for name, mid in NAME_TO_ID.items():
        d = disp.get(name)
        if not d:
            continue
        c = cap.get(mid, {"tier": "T0", "measured": False, "basis": "unknown"})
        cap_rank = TIER_RANK.get(c["tier"], 0)
        disp_rank = _disposition_rank(d["score"]) if d["score"] is not None else 0
        emp_rank = min(cap_rank, disp_rank)
        binding = ("both" if cap_rank == disp_rank
                   else "disposition" if disp_rank < cap_rank else "capability")
        price = models.get(mid, {})
        rows.append({
            "model": DISPLAY.get(mid, mid),
            "id": mid,
            "price_in": price.get("input_per_1M"),
            "price_out": price.get("output_per_1M"),
            "capability": {**c, "rank": cap_rank},
            "disposition": {
                "score": d["score"], "max": d["max"],
                "p8_caught": d["p8_caught"], "p8_score": d["p8_score"],
                "effort_flat": d["effort_flat"], "per_effort": d["per_effort"],
                "evidence_class": d["evidence_class"], "lineage_flag": d["lineage_flag"],
                "n_gradings": d["n_gradings"], "rank": disp_rank,
            },
            "employee": {
                "rank": emp_rank, "label": LEVEL_LABEL[emp_rank], "binding_axis": binding,
            },
        })
    rows.sort(key=lambda r: (-r["employee"]["rank"], -r["capability"]["rank"], -(r["disposition"]["score"] or 0)))

    total_gradings = sum(r["disposition"]["n_gradings"] for r in rows)
    n_cells = len(aggregate(data_dir))
    return {
        "_meta": {
            "what": "2-D employee tally: capability tier x disposition -> employee level",
            "rule": "employee level = min(capability_rank, disposition_rank) — trust caps skill",
            "disposition": {
                "evidence": "MEASURED",
                "source": "data/control-results (ten probes, 2/1/0), pooled by scripts/aggregate_control.py",
                "gradings": total_gradings,
                "cells": n_cells,
                "counts_note": f"{total_gradings} grade observations across {n_cells} probe cells "
                               "(Fable's two independent runs add the extra observations)",
                "effort_note": "flat on effort — disposition lives in the weights, not compute",
                "residual": "P8 (the planted %2F bug) is the frontier residual: haiku misses it at any effort",
            },
            "capability": {
                "evidence": "MEASURED" if results_path and Path(results_path).exists() else "DECLARED",
                "source": (f"{Path(results_path).name} pass-rates" if results_path and Path(results_path).exists()
                           else "models.json tier_ceiling — no capability run in data/results/ yet"),
                "how_to_measure": "run the benchmark, then: python scripts/build_tally.py --results <harness_results.jsonl>",
            },
            "escape_hatch": "a disposition-capped model rises under a driver/hands harness with a frozen policy (driver/policy/)",
        },
        "rows": rows,
        "coverage": coverage(disp, cap, models),
    }


def _fmt(t: dict) -> str:
    lines = []
    m = t["_meta"]
    lines.append(f"disposition: {m['disposition']['evidence']} ({m['disposition']['gradings']} gradings)   "
                 f"capability: {m['capability']['evidence']}")
    lines.append(f"{'model':11}{'cap':>5}{'disp':>7}{'P8':>5}  employee level")
    for r in t["rows"]:
        d, c, e = r["disposition"], r["capability"], r["employee"]
        p8 = "✓" if d["p8_caught"] else "✗"
        flat = " (flat)" if d["effort_flat"] else ""
        cap = c["tier"] + ("" if c["measured"] else "*")
        lines.append(f"{r['model']:11}{cap:>5}{str(d['score'])+'/20':>7}{p8:>5}  {e['label']}"
                     f"   [binds: {e['binding_axis']}]{flat}")
    lines.append("* = declared ceiling, not measured (no capability run yet)")
    cov = t["coverage"]; tot = cov["totals"]
    lines.append("")
    lines.append(f"reachable universe: {tot['models_registered']} models across "
                 f"{tot['backends_implemented']} implemented backends "
                 f"({tot['disposition_measured']} disposition-measured, {tot['capability_measured']} capability-measured)")
    for p in cov["providers"]:
        gate = "local, no key" if p["local"] else (p["gate"] or "")
        ids = ", ".join(m["id"] for m in p["models"]) or "— bring your endpoint (base_url), no code"
        lines.append(f"  {p['label']:22} [{gate}]  {p['n_models']}: {ids}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/control-results")
    ap.add_argument("--results", default=None, help="a real harness_results.jsonl to measure capability from")
    ap.add_argument("--print", action="store_true", dest="show", help="print the tally; write nothing")
    a = ap.parse_args()

    tally = build(a.data, a.results)
    print(_fmt(tally))
    if a.show:
        return
    body = json.dumps(tally, indent=2, ensure_ascii=False)
    (REPO / "data" / "tally.json").write_text(body + "\n", encoding="utf-8")
    (REPO / "site" / "tally.json").write_text(body + "\n", encoding="utf-8")
    print("\nwrote data/tally.json and site/tally.json")


if __name__ == "__main__":
    main()
