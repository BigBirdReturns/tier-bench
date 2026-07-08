#!/usr/bin/env python3
"""
Which tasks are valid for capability breadth-mapping — and which are answer-key theatre.

An agentic solver (haiku iterating, or any model that can run the tests) will read
whatever grader it can see and brute it. So a task only measures *capability* if the
deciding grader is HIDDEN from the solver. The rule, enforced here:

  breadth-valid  == ships a hidden grader the solver never sees. The solver may only
                    see a weak `visible_tests.py` / the spec; the hidden grader
                    produces the score. "The loop can only buy what visible selection
                    can see; the hidden set says whether that bought real quality."

  NOT breadth-valid == the grader is the file the solver edits/runs (the `tasks/*.json`
                    manifests: solver edits input.py, grader IS `python input.py`).
                    Fine for the router benchmark's one-shot grading; USELESS for
                    capability mapping, because an agentic solver reads the tests.

Today the hidden-grader (breadth-valid) set is small and real: task01, task02,
task06 in experiments/tier-uplift. That is the honest ruler. Grow it by AUTHORING
tasks with visible/hidden daylight — not by pointing the run at gameable ones.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UPLIFT = REPO / "experiments" / "tier-uplift"

# Filenames that are a hidden grader (produce the score, never shown to the solver).
HIDDEN_GRADER_NAMES = ("hidden_tests.py", "hidden_oracle.py", "grader.py")


def breadth_valid_tasks(root: Path = UPLIFT) -> list[dict]:
    """Tier-uplift tasks that ship a hidden grader — the only ones valid for
    capability breadth-mapping."""
    out = []
    for d in sorted(root.glob("task*")):
        if not d.is_dir():
            continue
        hidden = [f.name for f in d.iterdir() if f.name in HIDDEN_GRADER_NAMES]
        if hidden:
            out.append({"task": d.name, "dir": str(d.relative_to(REPO)),
                        "hidden_grader": hidden[0]})
    return out


def is_gameable(manifest_or_dir: str | Path) -> bool:
    """True if the solver can see the deciding grader. The tasks/*.json format is
    always gameable (target == the graded file)."""
    p = Path(manifest_or_dir)
    if p.suffix == ".json":
        return True  # tasks/ manifests: solver edits the file the grader runs
    if p.is_dir():
        return not any((p / n).exists() for n in HIDDEN_GRADER_NAMES)
    return True


if __name__ == "__main__":
    valid = breadth_valid_tasks()
    print(f"breadth-valid (hidden-grader) tasks: {len(valid)}")
    for t in valid:
        print(f"  {t['task']:24s} hidden grader: {t['hidden_grader']}  ({t['dir']})")
    print("\nNOT breadth-valid (visible grader — an agentic solver reads the answer key):")
    print("  every tasks/*.json manifest  (solver edits input.py; grader is `python input.py`)")
    print("  tier-uplift task03/04/05/07  (no hidden grader file)")
    print("\nMap on the valid set only. Grow it by authoring visible/hidden-daylight tasks.")
