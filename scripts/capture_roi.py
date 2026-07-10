#!/usr/bin/env python3
"""Compute frontier-capture ROI: projection vs. measured, never confused.

For each capture in data/capture/*.jsonl this answers the economic question the
ledger exists for: was expensive cognition converted into machinery, and when
does it break even?

The reading of the two paths (docs/frontier-capture.md):
  - new_path  = the frontier call being RETIRED (what you'd pay without the artifact)
  - old_path  = the floor the replay runs on (what you pay with it)
  - savings_per_replay = new_path.cost - old_path.cost
  - projected_break_even = ceil(capture_cost / savings_per_replay)

Discipline (burden rules, enforced in what this prints — not just in prose):
  - The projection is computed at read time and labeled PROJECTED. It is never
    written back to the ledger; break_even_reuse_count stays null until replays
    are validated (validate_capture_ledger.py rejects otherwise).
  - Amortization state is measured-only: validated_replays vs the projection.
    Zero replays -> needs_replay, no matter how good the projection looks.
  - Mixed cost bases (e.g. real-billed capture over a shadow-estimated floor)
    are named in the output: a projection is only as hard as its softest basis.
  - Missing costs -> ROI: UNMEASURED. Absence of data is an answer, not a gap
    to fill with a guess.

    python scripts/capture_roi.py            # human table
    python scripts/capture_roi.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_math import projected_break_even, savings_per_replay  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CAPTURE_DIR = REPO / "data/capture"


def load_captures(directory: Path = CAPTURE_DIR) -> list[dict]:
    rows = []
    for f in sorted(directory.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("record_type") == "capture":
                    rows.append(row)
    return rows


def roi_for(cap: dict) -> dict:
    """Pure function: one capture row -> its ROI report."""
    out = {
        "capture_id": cap.get("capture_id"),
        "capture_cost_usd": cap.get("capture_cost_usd"),
        "capture_cost_basis": cap.get("cost_basis"),
        "validated_replays": cap.get("validated_replays", 0),
    }
    old_c = (cap.get("old_path") or {}).get("cost_usd_per_trial")
    new_c = (cap.get("new_path") or {}).get("cost_usd_per_trial")
    if old_c is None or new_c is None:
        out.update(roi_state="UNMEASURED",
                   note="old/new path costs missing — no projection; absence of data is the answer")
        return out
    savings = savings_per_replay(old_c, new_c)
    if savings <= 0:
        out.update(roi_state="NO_SAVINGS",
                   savings_per_replay_usd=round(savings, 6),
                   note="floor path is not cheaper than the retired call — capture cannot amortize on cost")
        return out
    projected = projected_break_even(cap["capture_cost_usd"], old_c, new_c)
    bases = {cap.get("cost_basis"),
             (cap.get("old_path") or {}).get("cost_basis"),
             (cap.get("new_path") or {}).get("cost_basis")} - {None}
    replays = cap.get("validated_replays", 0)
    out.update(
        savings_per_replay_usd=round(savings, 6),
        projected_break_even_replays=projected,
        cost_basis_mix=sorted(bases),
        basis_caveat=("uniform" if len(bases) == 1 else
                      "MIXED — projection is only as hard as its softest basis"),
        roi_state=("amortized" if replays >= projected and replays > 0 else
                   "amortizing" if replays > 0 else
                   "needs_replay"),
        replays_remaining_to_break_even=max(projected - replays, 0),
        retired_value_usd=round(replays * savings, 6),
    )
    if replays == 0:
        out["note"] = ("projection only — zero validated replays; the floor+artifact path "
                       "has not been proven against the hidden grader")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    caps = load_captures()
    if not caps:
        print("no capture rows found", file=sys.stderr)
        return 1
    reports = [roi_for(c) for c in caps]
    if a.json:
        print(json.dumps(reports, indent=1))
        return 0
    for r in reports:
        print(f"capture: {r['capture_id']}")
        print(f"  capture cost      : ${r['capture_cost_usd']} ({r['capture_cost_basis']})")
        if r["roi_state"] in ("UNMEASURED", "NO_SAVINGS"):
            print(f"  ROI               : {r['roi_state']} — {r['note']}")
            print()
            continue
        print(f"  savings/replay    : ${r['savings_per_replay_usd']} "
              f"(basis mix: {', '.join(r['cost_basis_mix'])} — {r['basis_caveat']})")
        print(f"  PROJECTED break-even: {r['projected_break_even_replays']} validated replays")
        print(f"  validated replays : {r['validated_replays']} "
              f"(remaining to break even: {r['replays_remaining_to_break_even']})")
        print(f"  retired value     : ${r['retired_value_usd']}")
        print(f"  ROI state         : {r['roi_state']}")
        if "note" in r:
            print(f"  note              : {r['note']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
