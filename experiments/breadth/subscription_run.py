#!/usr/bin/env python3
"""Generate public prompt packets for ChatGPT UI subscription-surface runs."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

def sha(s: str) -> str: return hashlib.sha256(s.encode()).hexdigest()
def label(fam: str, intel: str, selected: str|None=None) -> str: return selected or f"{fam} / {intel}"
def prompt_for(task_id: str) -> str:
    p = REPO / "experiments/tier-uplift" / task_id / "spec.md"
    return p.read_text(encoding="utf-8")

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-family", required=True); ap.add_argument("--intelligence", required=True)
    ap.add_argument("--selected-model-label"); ap.add_argument("--task-id", required=True); ap.add_argument("--phase", default="solo")
    ap.add_argument("--trial", type=int, default=1); ap.add_argument("--out")
    a = ap.parse_args(); prompt = prompt_for(a.task_id); selected = label(a.model_family, a.intelligence, a.selected_model_label)
    packet = {"capture_id": f"{a.model_family}__{a.intelligence}__{a.task_id}__trial{a.trial}".replace(" / ", "__"),
              "model_family": a.model_family, "intelligence": a.intelligence, "selected_model_label": selected,
              "task_id": a.task_id, "phase": a.phase, "trial": a.trial, "visible_thought_seconds": None,
              "prompt_text": prompt, "prompt_sha256": sha(prompt), "raw_output": "", "screenshot_sha256": None, "quota_status": ""}
    text = json.dumps(packet, indent=2)
    if a.out: Path(a.out).write_text(text+"\n", encoding="utf-8")
    else: print(text)
    return 0
if __name__ == "__main__": raise SystemExit(main())
