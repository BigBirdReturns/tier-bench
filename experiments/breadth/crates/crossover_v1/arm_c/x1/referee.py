#!/usr/bin/env python3
"""Frozen referee for X1: burn_report.py --vendor filter. Exit 0 = PASS.

Deterministic, self-contained: builds a synthetic sentinel-state dir with one
anthropic session and checks the specified behaviors only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
SCRIPT = ROOT / "scripts" / "burn_report.py"
SID = "x1-synthetic-anthropic"


def run(extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=120,
    )


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def parse_json(r, label):
    if r.returncode != 0:
        fail(f"{label}: exit {r.returncode}: {(r.stderr or '').strip()[:200]}")
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines:
        fail(f"{label}: no output")
    try:
        return json.loads(lines[-1])
    except Exception as e:
        fail(f"{label}: output not JSON: {e}")


def main():
    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "state"
        state.mkdir()
        (state / f"{SID}.json").write_text(
            json.dumps({"cost_usd": 1.23, "tier": "T1"}), encoding="utf-8")
        base = ["--state-dir", str(state)]

        # 1. Without --vendor: JSON behavior unchanged (both vendor keys, row present)
        obj = parse_json(run(base + ["--json"]), "baseline --json")
        if set(obj.get("vendors", {}).keys()) != {"anthropic", "openai"}:
            fail(f"baseline vendors keys wrong: {sorted(obj.get('vendors', {}))}")
        sids = [s.get("sid") for s in obj.get("sessions", [])]
        if SID not in sids:
            fail("baseline --json lost the synthetic anthropic session")

        # 2. --vendor anthropic: vendors has ONLY anthropic; rows filtered to it
        obj = parse_json(run(base + ["--json", "--vendor", "anthropic"]),
                         "--vendor anthropic")
        if set(obj.get("vendors", {}).keys()) != {"anthropic"}:
            fail(f"--vendor anthropic: vendors keys = {sorted(obj.get('vendors', {}))}, want only anthropic")
        rows = obj.get("sessions", [])
        bad = [s for s in rows if s.get("vendor") != "anthropic"]
        if bad:
            fail(f"--vendor anthropic: {len(bad)} non-anthropic session rows leaked")
        if SID not in [s.get("sid") for s in rows]:
            fail("--vendor anthropic: synthetic anthropic session missing from rows")

        # 3. --vendor openai: vendors has ONLY openai; anthropic rows excluded
        obj = parse_json(run(base + ["--json", "--vendor", "openai"]),
                         "--vendor openai")
        if set(obj.get("vendors", {}).keys()) != {"openai"}:
            fail(f"--vendor openai: vendors keys = {sorted(obj.get('vendors', {}))}, want only openai")
        rows = obj.get("sessions", [])
        bad = [s for s in rows if s.get("vendor") != "openai"]
        if bad:
            fail(f"--vendor openai: {len(bad)} non-openai session rows leaked")
        if SID in [s.get("sid") for s in rows]:
            fail("--vendor openai: anthropic session leaked into rows")

        # 4. Invalid vendor rejected (spec: --vendor {anthropic,openai})
        r = run(base + ["--json", "--vendor", "bogus"])
        if r.returncode == 0:
            fail("--vendor bogus accepted; choices not enforced")

        # 5. Text mode without --vendor still works
        r = run(base)
        if r.returncode != 0:
            fail(f"text mode without --vendor broke: exit {r.returncode}")

    print("PASS: X1 referee ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
