#!/usr/bin/env python3
"""Smoke test for the UI-capture lane: packet -> ingest -> local hidden grade ->
ledger row + matrix. Runs against temp files only ($0, no live model, no real
ledger touched). Exits non-zero on any broken invariant.

    python experiments/breadth/ui_capture_smoke.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# A known-valid task01 answer in raw_function_only form (self-contained def,
# no markdown fence) — the REAL hidden grader must score it 38/38 at ingest.
VALID_RAW = '''def parse_duration(s):
    import re
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", s)
    if not m or not any(m.groups()):
        raise ValueError("invalid duration")
    h, mi, se = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + se
'''


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"FAIL: {' '.join(cmd)}\n{p.stdout}{p.stderr}")
    return p.stdout


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # 1. generate a real public packet, then fill in the "captured" answer
        pkt_path = tdp / "pkt.json"
        run([sys.executable, "experiments/breadth/subscription_run.py",
             "--model-family", "SMOKE-FAM", "--intelligence", "Instant",
             "--task-id", "task01_parse_duration", "--trial", "1", "--out", str(pkt_path)])
        pkt = json.loads(pkt_path.read_text())
        assert pkt["prompt_sha256"] and pkt["raw_output"] == ""
        for bad in ("hidden_tests.py", "hidden_oracle.py", "answer_key"):
            assert bad not in pkt["prompt_text"], f"hidden artifact leaked: {bad}"
        pkt["raw_output"] = VALID_RAW

        # 2. an unavailable selector cell (blocked row)
        blocked = {"capture_id": "smoke__o3__Medium__task01__trial1",
                   "model_family": "o3", "intelligence": "Medium",
                   "task_id": "task01_parse_duration", "phase": "solo", "trial": 1,
                   "prompt_text": pkt["prompt_text"], "raw_output": "",
                   "quota_status": "not_exposed_in_ui"}

        captures = tdp / "captures.jsonl"
        captures.write_text(json.dumps(pkt) + "\n" + json.dumps(blocked) + "\n")

        ledger, norm, matrix = tdp / "ledger.jsonl", tdp / "norm.jsonl", tdp / "matrix.json"
        run([sys.executable, "experiments/breadth/ui_capture_ingest.py", str(captures),
             "--ledger", str(ledger), "--normalized-out", str(norm), "--matrix-out", str(matrix)])

        rows = [json.loads(x) for x in ledger.read_text().splitlines()]
        assert len(rows) == 2, f"want 2 ledger rows, got {len(rows)}"
        good, blk = rows
        e = good["extra"]
        for field in ("prompt_sha256", "raw_output_sha256", "candidate_sha256",
                      "selected_model_family", "selected_intelligence", "format_compliance"):
            assert e.get(field), f"missing extra.{field}"
        assert e["score"] == "SCORE 38/38", f"hidden grade: {e['score']}"
        assert good["outcome"] == "pass"
        assert all(good[f] == 0 for f in ("input_tokens", "output_tokens", "cost_usd")), "token/cost must be zero"

        assert blk["outcome"] == "blocked", blk["outcome"]
        assert blk["extra"]["quota_status"] == "not_exposed_in_ui"

        mx = json.loads(matrix.read_text())
        cells = mx["task01_parse_duration"]
        assert "SMOKE-FAM" in cells and "o3" in cells, f"matrix families: {list(cells)}"
        assert cells["o3"]["Medium"]["1"]["availability"] == "not_exposed_in_ui"

    print("UI CAPTURE SMOKE OK — packet has no hidden artifacts; valid capture "
          "hidden-graded 38/38 at ingest; blocked cell recorded; matrix carries both.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
