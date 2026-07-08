#!/usr/bin/env python3
"""Generate public prompt packets for ChatGPT UI subscription-surface runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC_TASK_FILES = ("spec.md", "subject.py", "visible_tests.py")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def label(fam: str, intel: str, selected: str | None = None) -> str:
    return selected or f"{fam} / {intel}"


def prompt_for(task_id: str) -> str:
    """Build the public UI prompt from task files that are safe to show solvers.

    Hidden graders, hidden oracles, answer keys, result logs, and usage logs are
    deliberately excluded. Missing optional public files are skipped so tasks that
    only ship a spec still work.
    """
    task_dir = REPO / "experiments/tier-uplift" / task_id
    if not task_dir.is_dir():
        raise FileNotFoundError(f"unknown task directory: {task_dir}")

    parts = [
        "You are solving a benchmark task. Return only the requested final answer format.",
        "Do not include prose, markdown fences, tests, or explanations unless the task explicitly asks for them.",
    ]
    found = False
    for name in PUBLIC_TASK_FILES:
        path = task_dir / name
        if not path.exists():
            continue
        found = True
        parts.append(f"\n--- {name} ---\n{path.read_text(encoding='utf-8').rstrip()}\n")
    if not found:
        raise FileNotFoundError(f"no public prompt files found in {task_dir}")
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-family", required=True)
    ap.add_argument("--intelligence", required=True)
    ap.add_argument("--selected-model-label")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--phase", default="solo")
    ap.add_argument("--trial", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()
    prompt = prompt_for(a.task_id)
    selected = label(a.model_family, a.intelligence, a.selected_model_label)
    packet = {
        "capture_id": f"{a.model_family}__{a.intelligence}__{a.task_id}__trial{a.trial}".replace(" / ", "__"),
        "model_family": a.model_family,
        "intelligence": a.intelligence,
        "selected_model_label": selected,
        "task_id": a.task_id,
        "phase": a.phase,
        "trial": a.trial,
        "visible_thought_seconds": None,
        "prompt_text": prompt,
        "prompt_sha256": sha(prompt),
        "raw_output": "",
        "screenshot_sha256": None,
        "quota_status": "",
    }
    text = json.dumps(packet, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
