#!/usr/bin/env python3
"""Validate the CART0 v2 run manifest — fail-closed.

A frozen manifest that nothing checks can drift into prose. This asserts the
invariants the design depends on: three arms A/B/C each with a boundary message,
the boundary message as the ONLY per-arm manipulation, the structural READY
first-response (no planning turn), a common boot map carrying the target rule,
balanced-block scheme with K>=1, the mandatory-preservation set, and the GATED
grading/disposition rules. Empty error list == valid.

    python validate_manifest.py manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARMS = ("A", "B", "C")
REQUIRED_PRESERVATION = {
    "boot_prompt_bytes", "every_message_and_response", "invocation_receipt",
    "administration_order", "abort_records",
}


def validate_manifest(m: dict) -> list[str]:
    errs: list[str] = []

    if m.get("manifest_version") != "cart0-abc-v2":
        errs.append("manifest_version must be 'cart0-abc-v2'")
    for key in ("estimand", "authority", "frozen"):
        if not (isinstance(m.get(key), str) and m[key].strip()):
            errs.append(f"{key} must be a non-empty string")

    boot = m.get("boot_map") or {}
    scaffold = boot.get("scaffold_block")
    if not (isinstance(scaffold, str) and "backslash is a literal member" in scaffold):
        errs.append("boot_map.scaffold_block must carry the target rule (the registered control)")

    proto = m.get("protocol") or {}
    if proto.get("first_response_exact") != "READY":
        errs.append("protocol.first_response_exact must be 'READY' (structural anti-rehearsal)")
    if proto.get("no_planning_turn") is not True:
        errs.append("protocol.no_planning_turn must be true — a planning turn reintroduces the v1 confound")

    arms = m.get("arms") or {}
    if set(arms) != set(ARMS):
        errs.append(f"arms must be exactly {list(ARMS)}")
    messages: dict[str, str] = {}
    for arm in ARMS:
        spec = arms.get(arm) or {}
        msg = spec.get("boundary_message")
        if not (isinstance(msg, str) and msg.strip()):
            errs.append(f"arm {arm} must have a non-empty boundary_message")
        else:
            messages[arm] = msg
        if not (isinstance(spec.get("role"), str) and spec["role"].strip()):
            errs.append(f"arm {arm} must name a role")
    # the boundary message is the ONLY manipulation → the three must differ
    if len(messages) == 3 and len(set(messages.values())) != 3:
        errs.append("the three arms' boundary_message values must all differ (the only manipulation)")
    # B must carry the applicable rule; A/C must not resurface it
    if "B" in messages and "backslash is a literal member" not in messages["B"]:
        errs.append("arm B (resurfaced) must restate the applicable rule at the boundary")
    for neutral in ("A", "C"):
        if neutral in messages and "backslash is a literal member" in messages[neutral]:
            errs.append(f"arm {neutral} must NOT resurface the target rule (it is a control)")

    blocking = m.get("blocking") or {}
    if blocking.get("scheme") != "balanced_blocks":
        errs.append("blocking.scheme must be 'balanced_blocks'")
    if list(blocking.get("order", [])) != list(ARMS):
        errs.append(f"blocking.order must be {list(ARMS)}")
    k = blocking.get("K")
    if not (isinstance(k, int) and not isinstance(k, bool) and k >= 1):
        errs.append("blocking.K must be an integer >= 1")

    preservation = set(m.get("preservation_required") or [])
    missing = REQUIRED_PRESERVATION - preservation
    if missing:
        errs.append(f"preservation_required is missing mandatory fields: {sorted(missing)}")

    grading = m.get("grading") or {}
    for key in ("hidden_grader", "seal_before_grading", "solver_off_scoring_path"):
        if grading.get(key) is not True:
            errs.append(f"grading.{key} must be true (GATED)")

    disp = m.get("disposition") or {}
    for key in ("aborted_mints", "ineligible_mints", "contaminated_mints"):
        if disp.get(key) != "neither":
            errs.append(f"disposition.{key} must be 'neither' (aborts/ineligibles mint neither pass nor fail)")
    if disp.get("verdict_requires") != "complete_balanced_blocks_with_preserved_transcripts":
        errs.append("disposition.verdict_requires must gate the verdict on complete blocks + preserved transcripts")

    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", nargs="?", default=str(Path(__file__).resolve().parent / "manifest.json"))
    a = ap.parse_args()
    errs = validate_manifest(json.loads(Path(a.manifest).read_text(encoding="utf-8")))
    if errs:
        for e in errs:
            print(f"ERROR {e}", file=sys.stderr)
        return 1
    print("PASS — CART0 v2 manifest holds its frozen invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
