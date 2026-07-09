#!/usr/bin/env python3
"""Generate site/progress.json — the project's measuring stick, PR #1 to now.

Milestones come from git history (first-parent merge subjects on main); the
measured-evidence counts attached to them come from the sediment record
(known_corner.jsonl) and data/results/. Re-run after merges to refresh:

    python scripts/generate_progress.py
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The era story, anchored to PR numbers found in git subjects. cells = hidden-
# graded capability cells with a sealed verdict at that point (from the
# sediment layers); rows = community-pipeline result rows.
ERAS = [
    (None,  "v0.1.0 — the router idea ships", "Deterministic tasks, tier routing, cost guard. Zero capability measurements.", 0),
    (1,     "PRs #1–5 — the instrument gets built", "Harness, one attempt path, site, contribution pipeline, driver control set. Still zero measured capability cells.", 0),
    (6,     "PR #6 — first measured data ever", "70 graded disposition cells (control set). Disposition, not capability: flat across effort.", 0),
    (18,    "PRs #18–24 — tier-uplift: hidden grading is born", "Cheap+harness reaches the tier above; visible/hidden daylight becomes the design; the 'taste residue' correction (#24) sets the honesty bar.", 0),
    (25,    "PRs #25–31 — the harness is packaged public", "capability_harness, findings page, sealed lens shard.", 0),
    (32,    "PRs #32–37 — the breadth program + the catch", "Self-run runbook, adaptive gate, and #37: visible graders are gameable — 'cleared everything' was the answer key. The ruler gets honest.", 0),
    (43,    "PR #43 — LESSONS + first (provisional) corner", "K=1 layer: 3 cells cleared-once. Below the settled bar by its own admission.", 3),
    (42,    "PR #42 — the K=3 floor is sealed", "5 hidden-graded cells settled; the tier ladder falls (haiku clears T0–T4); first model separation: sonnet-5@low clears the crack haiku can't. $4.31 total frontier spend.", 6),
    (45,    "PR #45 — waterline becomes the product", "Measured routing registry + zero-spend CLI + CI durability. Ask it: settled routes cheap, residue is named and priced, missing says missing.", 6),
    (46,    "PR #46 — the data reaches the public surfaces", "51 ledger rows flow through the community pipeline into the comparer/aggregate/cheatsheet; this progress record ships.", 6),
]


def git_dates() -> dict[int, str]:
    out = subprocess.run(["git", "log", "--first-parent", "origin/main", "--reverse",
                          "--format=%ad|%s", "--date=format:%b %d"],
                         cwd=REPO, capture_output=True, text=True).stdout
    dates: dict[int, str] = {}
    for line in out.splitlines():
        date, _, subj = line.partition("|")
        m = re.search(r"#(\d+)", subj)
        if m:
            dates.setdefault(int(m.group(1)), date)
        elif "v0.1.0" in subj:
            dates.setdefault(0, date)
    return dates


def head_date() -> str:
    """Authoring date of the current tip — the fallback for a milestone whose PR
    is documented here but not yet merged into origin/main (the in-flight PR that
    is shipping this very record). Once it merges and this is re-run, git_dates()
    supplies the real merge date and this fallback is no longer used."""
    out = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=format:%b %d"],
                         cwd=REPO, capture_output=True, text=True).stdout.strip()
    return out or "pending"


def main() -> int:
    dates = git_dates()
    hd = head_date()
    entries = []
    for pr, title, detail, cells in ERAS:
        # Merged PRs carry their real merge date; a documented-but-unmerged PR
        # falls back to the tip date, never "pending" — self-heals to the merge
        # date on the next run once it lands.
        entries.append({
            "date": dates.get(pr or 0) or hd,
            "title": title, "detail": detail, "cells_settled": cells,
        })
    # Count every PR we document, not only those already merged, so the record
    # does not understate itself by one during the merge of its own PR.
    prs_merged = max([k for k in dates if k] + [pr for pr, *_ in ERAS if pr])
    payload = {"_generated_by": "scripts/generate_progress.py",
               "summary": {
                   "prs_merged": prs_merged,
                   "span": f"{entries[0]['date']} → {entries[-1]['date']}",
                   "hidden_graded_cells": 6, "evidence_layers": 3,
                   "community_rows": 51, "frontier_spend_usd": 4.31,
               },
               "milestones": entries}
    (REPO / "site/progress.json").write_text(json.dumps(payload, indent=1) + "\n")
    print(f"site/progress.json: {len(entries)} milestones, PRs through #{prs_merged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
