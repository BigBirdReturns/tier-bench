#!/usr/bin/env python3
"""Emit a scaffold packet from the sediment layer — captured judgment, portable.

The sediment (waterline.json, sealed evidence layers) already contains the
expensive part of every solved task: WHICH model clears it, at what cost, and —
for residue cells — the NAMED rule commitment that separated models. This script
turns that into a **scaffold packet**: a compact, deterministic context block you
paste into any project's CLAUDE.md / system prompt / solver preamble, so the next
solver (haiku or Fable — input-side entropy control helps the top model too)
starts holding the captured commitments instead of re-deriving them.

No model on the emission path. Reads only the sealed waterline surface; anything
not measured is stated as unmeasured, never guessed. Each packet cites its
evidence layers so the scaffold is auditable back to sediment.

This is the replay artifact the capture ledger (ROADMAP: frontier capture ledger)
counts: every project that solves with a packet instead of a frontier call is one
validated_replay toward break-even.

    python scripts/emit_scaffold.py                     # full packet, markdown
    python scripts/emit_scaffold.py --task task02_wildcard
    python scripts/emit_scaffold.py --format json       # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WATERLINE = REPO / "experiments/breadth/run/waterline.json"

# The standing discipline rules a scaffold carries with it — short form of
# experiments/breadth/LESSONS.md. These travel with every packet because the
# packet is useless (or dangerous) without its usage law.
DISCIPLINE = [
    "Trust only what the packet cites: a claim without an evidence layer is unmeasured, not false and not true.",
    "DO NOT ESCALATE past the cheapest listed model for a settled cell; the floor is measured, not guessed.",
    "Hold the listed residue commitments as fixed rule interpretations — do not re-derive or second-guess them mid-solve.",
    "If your task is not listed, the sediment says nothing about it: route by your own judgment and say so.",
]


def load_waterline(path: Path = WATERLINE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_packet(w: dict, task: str | None = None) -> dict:
    """Assemble the packet as data; rendering is a separate concern."""
    floor = w.get("settled_floor", {})
    residue = w.get("judgment_residue", {})
    if task is not None:
        if task in floor:
            floor, residue = {task: floor[task]}, {}
        elif task in residue:
            floor, residue = {}, {task: residue[task]}
        else:
            # Unmeasured is a first-class answer, same as waterline.py itself.
            return {"generated_from": str(WATERLINE.relative_to(REPO)),
                    "task": task, "status": "UNMEASURED",
                    "note": "No sediment for this task. The scaffold makes no claim.",
                    "discipline": DISCIPLINE}
    layers = sorted({c["evidence_layer"]
                     for c in list(floor.values()) + list(residue.values())
                     if c.get("evidence_layer")})
    return {
        "generated_from": str(WATERLINE.relative_to(REPO)),
        "waterline_generated": w.get("_generated"),
        "rule": w.get("_rule"),
        "evidence_layers": layers,
        "routing_floor": {
            tid: {"model": c["cheapest_measured"], "rung": c.get("rung"),
                  "score": c.get("score"), "cost_usd_per_trial": c.get("cost_usd_per_trial"),
                  "cost_basis": c.get("cost_basis"), "caveats": c.get("caveats", [])}
            for tid, c in floor.items()
        },
        "residue_commitments": {
            tid: {"commitment": c.get("residue_name"),
                  "cheapest_measured": c.get("cheapest_measured"), "rung": c.get("rung"),
                  "floor_instability": c.get("floor_instability"),
                  "cost_usd_per_trial": c.get("cost_usd_per_trial"),
                  "cost_basis": c.get("cost_basis"), "caveats": c.get("caveats", [])}
            for tid, c in residue.items()
        },
        "discipline": DISCIPLINE,
    }


def render_md(p: dict) -> str:
    if p.get("status") == "UNMEASURED":
        return (f"## Scaffold packet — {p['task']}: UNMEASURED\n\n"
                f"{p['note']}\n\nSource: `{p['generated_from']}`\n")
    lines = [
        "## Scaffold packet — captured judgment from the tier-bench sediment",
        "",
        f"Source: `{p['generated_from']}` (generated {p['waterline_generated']}); "
        f"evidence layers: {', '.join(f'`{l}`' for l in p['evidence_layers']) or 'none'}.",
        f"Honesty rule: {p['rule']}",
        "",
    ]
    if p["residue_commitments"]:
        lines += ["### Rule commitments (hold these; do not re-derive)", ""]
        for tid, c in p["residue_commitments"].items():
            lines += [
                f"- **{tid}** — {c['commitment']}.",
                f"  Floor instability without this commitment: {c['floor_instability']}.",
                f"  Cleared by {c['cheapest_measured']} @ {c['rung']} "
                f"(${c['cost_usd_per_trial']}/trial, {c['cost_basis']}).",
            ]
            lines += [f"  Caveat: {cv}" for cv in c["caveats"]]
        lines.append("")
    if p["routing_floor"]:
        lines += ["### Routing floor (settled — route here, do not spend up)", "",
                  "| task | cheapest measured | score | $/trial (basis) |",
                  "|---|---|---|---|"]
        for tid, c in p["routing_floor"].items():
            lines.append(f"| {tid} | {c['model']} ({c['rung']}) | {c['score']} "
                         f"| {c['cost_usd_per_trial']} ({c['cost_basis']}) |")
        lines.append("")
        for tid, c in p["routing_floor"].items():
            for cv in c["caveats"]:
                lines.append(f"- caveat ({tid}): {cv}")
        if any(c["caveats"] for c in p["routing_floor"].values()):
            lines.append("")
    lines += ["### Usage discipline (travels with the packet)", ""]
    lines += [f"{i}. {d}" for i, d in enumerate(p["discipline"], 1)]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", help="emit for one task id (UNMEASURED if absent from sediment)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    a = ap.parse_args()
    packet = build_packet(load_waterline(), a.task)
    if a.format == "json":
        print(json.dumps(packet, indent=1))
    else:
        print(render_md(packet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
