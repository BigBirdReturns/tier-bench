#!/usr/bin/env python3
"""
Let the run improve itself — without letting it grade itself.

Giving the model the ability to think about the harness and adjust as it learns is
powerful. It is also the exact shape of reward hacking: a model that can loosen its
own grader to make a task "pass" will, and then the breadth map is a lie. Anthropic's
own J-lens work catches model organisms whose workspace lights up with "fake",
"secretly", "trick" on ordinary tasks; this repo's whole thesis is to take the
stochastic processor OFF the authority path. So the capability ships with a bright
line, enforced here, not just asked for:

  FREE  — apply immediately, just log it. These change HOW the run works, not what
          it measures: solve strategy, prompt wording, which lenses to use, trial/
          retry policy within K, task ordering, tuning the effort ladder.

  GATED — never self-apply mid-run. These change WHAT COUNTS AS PASSING: a task's
          grader, the pass criteria, a task definition, skipping/disabling a task,
          or any ledger change that could hide cost. The model may only *propose*
          them (logged here) for a human to review and apply upstream.

Everything — free adjustments made and gated proposals raised — appends to an
append-only harness_log.jsonl, so "why did the map change shape?" always has an
auditable answer.

    from experiments.breadth.adapt import record, pending_proposals
    record(log, kind="adjustment", target="effort_ladder", change="added xhigh before max",
           rationale="high->max was too big a jump on t3_*", applied=True)   # FREE -> applied
    record(log, kind="proposal", target="grader", change="t3_x grader rejects a valid fix (Y)",
           rationale="...", applied=True)   # GATED -> forced to applied=False, queued for review
"""
from __future__ import annotations

import json
from pathlib import Path

FREE = {"solve_strategy", "prompt", "lens_selection", "trial_policy", "ordering", "effort_ladder"}
GATED = {"grader", "pass_criteria", "task_definition", "disable_task", "skip_task",
         "ledger_schema", "cost_accounting"}


def classify(target: str) -> str:
    """'gated' if the change touches what counts as passing; else 'free'.
    Unknown targets are treated as GATED — fail safe, not open."""
    if target in FREE:
        return "free"
    return "gated"


def record(log_path: str | Path, kind: str, target: str, change: str,
           rationale: str, applied: bool, ts: str = "1970-01-01T00:00:00Z") -> dict:
    """Append one harness observation/adjustment/proposal. GATED targets are FORCED
    to applied=False no matter what is passed — the model cannot self-apply a change
    to its own scoring. Returns the row written."""
    cls = classify(target)
    if cls == "gated":
        applied = False  # hard gate: scoring changes are proposals only, never self-applied
    row = {
        "ts": ts, "kind": kind, "target": target, "class": cls,
        "change": change, "rationale": rationale, "applied": applied,
        "needs_human_review": cls == "gated",
    }
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def load(log_path: str | Path) -> list[dict]:
    p = Path(log_path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def pending_proposals(log_path: str | Path) -> list[dict]:
    """Gated proposals awaiting human review (the map can't be trusted to have
    incorporated these — they touch scoring and were NOT self-applied)."""
    return [r for r in load(log_path) if r.get("class") == "gated"]


if __name__ == "__main__":
    import sys
    log = sys.argv[1] if len(sys.argv) > 1 else "experiments/breadth/run/harness_log.jsonl"
    props = pending_proposals(log)
    print(f"{len(props)} gated proposal(s) awaiting human review in {log}")
    for r in props:
        print(f"  - [{r['target']}] {r['change']}  (applied={r['applied']})")
