#!/usr/bin/env python3
"""CART0 v2 runner — executes the frozen manifest with MANDATORY custody capture.

This is the harness that produces the administration transcript v1 did not: for
every trial it preserves the boot prompt bytes, every turn's message and response,
the invocation receipt, the administration order, and abort records. It enforces
the structural anti-rehearsal gate (a fixed-format `READY` first response) and the
balanced-block schedule, seals candidates before grading, and refuses a
comparative readout unless the blocks are complete with preserved transcripts.

It is KEYLESS: no model is called here. Inject a `solver` callable; a real run
wraps Agent-tool subagents, tests inject a deterministic fake. The whole point is
that the transcript exists and is hash-bound regardless of who the solver is.

    solver(ctx) -> {"response": str, "candidate": bytes|None,
                    "aborted": bool, "receipt": dict|None}
      ctx = {"turn": 1|2, "prompt": str, "arm": "A", "block": k, "trial_id": str}
    grader(candidate_bytes) -> {"passed": bool, "detail": str}
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_experiment(
    manifest: dict,
    solver: Callable[[dict], dict],
    grader: Callable[[bytes], dict],
    *,
    item_spec_bytes: bytes,
    out_dir: str | Path,
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidates").mkdir(exist_ok=True)

    # boot prompt = the bare item spec + the manifest's scaffold block (exact bytes)
    boot_prompt = item_spec_bytes + manifest["boot_map"]["scaffold_block"].encode("utf-8")
    (out / "boot_prompt.txt").write_bytes(boot_prompt)
    boot_sha = _sha(boot_prompt)
    boot_text = boot_prompt.decode("utf-8", "replace")

    arms = manifest["arms"]
    order = manifest["blocking"]["order"]
    K = manifest["blocking"]["K"]

    trials: list[dict] = []
    order_index = 0
    for block in range(1, K + 1):
        for arm in order:                       # balanced blocks: A,B,C each block
            trial_id = f"block{block}/{arm}"
            transcript: list[dict] = []
            rec: dict[str, Any] = {"trial_id": trial_id, "arm": arm, "block": block,
                                   "order_index": order_index, "boot_prompt_sha256": boot_sha}
            order_index += 1

            # turn 1 — deliver the common boot map; require exactly READY
            r1 = solver({"turn": 1, "prompt": boot_text, "arm": arm, "block": block, "trial_id": trial_id})
            transcript.append({"turn": 1, "prompt": boot_text, "response": r1.get("response", ""),
                               "receipt": r1.get("receipt") or {"usage_available": False}})
            if r1.get("aborted"):
                rec.update(outcome="aborted", transcript=transcript, note="aborted at boot turn")
                trials.append(rec)
                continue
            if (r1.get("response") or "").strip() != manifest["protocol"]["first_response_exact"]:
                # the solver rehearsed instead of the fixed READY — contaminated,
                # mints neither pass nor fail (the v1 confound, structurally caught)
                rec.update(outcome="contaminated", transcript=transcript,
                           note="first response was not the fixed READY token")
                trials.append(rec)
                continue

            # turn 2 — deliver the arm's boundary message (the only manipulation)
            boundary = arms[arm]["boundary_message"]
            r2 = solver({"turn": 2, "prompt": boundary, "arm": arm, "block": block, "trial_id": trial_id})
            transcript.append({"turn": 2, "prompt": boundary, "response": r2.get("response", ""),
                               "receipt": r2.get("receipt") or {"usage_available": False}})
            candidate = r2.get("candidate")
            if r2.get("aborted") or not isinstance(candidate, (bytes, bytearray)):
                rec.update(outcome="ineligible", transcript=transcript,
                           note="no candidate produced" if not r2.get("aborted") else "aborted at boundary turn")
                trials.append(rec)
                continue

            # SEAL the candidate before grading; solver is off the scoring path
            candidate = bytes(candidate)
            cand_path = out / "candidates" / f"block{block}_{arm}.py"
            cand_path.write_bytes(candidate)
            cand_sha = _sha(candidate)
            g = grader(candidate)                # hidden grader, injected
            rec.update(outcome=("pass" if g.get("passed") else "fail"),
                       candidate_sha256=cand_sha, grader_detail=g.get("detail", ""),
                       transcript=transcript)
            trials.append(rec)

    # write the custody artifacts
    with (out / "administration.jsonl").open("w", encoding="utf-8") as fh:
        for t in trials:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")

    readout = comparative_readout(trials, manifest)
    receipt = {"manifest_version": manifest["manifest_version"], "boot_prompt_sha256": boot_sha,
               "K": K, "n_trials": len(trials), "readout": readout}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    return receipt


def comparative_readout(trials: list[dict], manifest: dict) -> dict:
    """Per-arm pass rates — but ONLY when the blocks are complete with preserved
    transcripts. Aborted/ineligible/contaminated trials mint neither pass nor
    fail; an incomplete design gets NO_VERDICT, never an invented conclusion.
    """
    order = manifest["blocking"]["order"]
    K = manifest["blocking"]["K"]
    eligible = [t for t in trials if t.get("outcome") in ("pass", "fail")]
    # every trial must carry a preserved transcript (custody)
    if any(not t.get("transcript") for t in trials):
        return {"state": "NO_VERDICT", "reason": "a trial is missing its preserved transcript"}
    # completeness: every (block, arm) cell must be eligible
    have = {(t["block"], t["arm"]) for t in eligible}
    want = {(b, a) for b in range(1, K + 1) for a in order}
    missing = want - have
    if missing:
        return {"state": "NO_VERDICT",
                "reason": f"{len(missing)} of {len(want)} cells not eligible "
                          f"(aborted/ineligible/contaminated mint neither); complete balanced blocks required",
                "eligible_cells": len(have)}
    per_arm = {}
    for arm in order:
        cells = [t for t in eligible if t["arm"] == arm]
        passes = sum(1 for t in cells if t["outcome"] == "pass")
        per_arm[arm] = {"n": len(cells), "pass": passes, "pass_rate": round(passes / len(cells), 3)}
    return {"state": "complete", "per_arm": per_arm,
            "note": "per-arm pass rates over complete balanced blocks with preserved transcripts; "
                    "sealing a comparative verdict remains an operator decision"}
