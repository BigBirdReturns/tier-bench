"""FROZEN REFEREE — crossover_v1. Deterministic; the only pass criterion.
Run from repo root after each arm: python experiments/breadth/crates/crossover_v1/referee.py
Prints per-task PASS/FAIL and a summary line ARM SCORE: n/3. Always exits 0
(the score is the datum; arms are compared, not gated).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
results = {}


def run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def report(task, ok, detail=""):
    results[task] = ok
    print(("PASS " if ok else "FAIL ") + task + (" — " + detail if detail else ""))


# X1: burn_report --vendor filter
try:
    ok = True
    detail = ""
    for vendor in ("anthropic", "openai"):
        r = run([PY, "scripts/burn_report.py", "--json", "--vendor", vendor])
        if r.returncode != 0:
            ok, detail = False, f"{vendor}: rc={r.returncode}"
            break
        d = json.loads(r.stdout)
        if sorted(d.get("vendors", {}).keys()) != [vendor]:
            ok, detail = False, f"{vendor}: vendors keys {sorted(d.get('vendors', {}).keys())}"
            break
    if ok:  # unfiltered behavior unchanged
        r = run([PY, "scripts/burn_report.py", "--json"])
        d = json.loads(r.stdout)
        ok = r.returncode == 0 and sorted(d.get("vendors", {}).keys()) == ["anthropic", "openai"]
        detail = "" if ok else "unfiltered run broken"
    report("X1_vendor_filter", ok, detail)
except Exception as e:  # noqa: BLE001
    report("X1_vendor_filter", False, repr(e))

# X2: crate_new --list
try:
    crates_dir = Path("experiments/breadth/crates")
    before = {p.name for p in crates_dir.iterdir() if p.is_dir()}
    r = run([PY, "scripts/crate_new.py", "--list", "--dir", str(crates_dir)])
    after = {p.name for p in crates_dir.iterdir() if p.is_dir()}
    ok = (r.returncode == 0 and "burn_two_vendors_v1" in r.stdout
          and "crossover_v1" in r.stdout and before == after)
    report("X2_crate_list", ok, f"rc={r.returncode} created={sorted(after - before)}")
except Exception as e:  # noqa: BLE001
    report("X2_crate_list", False, repr(e))

# X3: dispatch --dry-run
try:
    with tempfile.TemporaryDirectory() as td:
        receipt = Path(td) / "receipt.md"
        r = run([PY, "scripts/dispatch.py", "--dry-run", "--arm-dir", ".",
                 "--hand-cmd", "echo HANDCMD-MARKER", "--referee", "echo REF-MARKER",
                 "--receipt", str(receipt)])
        ok = (r.returncode == 0 and "HANDCMD-MARKER" in r.stdout
              and "REF-MARKER" in r.stdout and not receipt.exists())
        report("X3_dispatch_dry_run", ok,
               f"rc={r.returncode} receipt_created={receipt.exists()}")
except Exception as e:  # noqa: BLE001
    report("X3_dispatch_dry_run", False, repr(e))

# Diff bound: only the three target scripts (+ their sibling-crate allowances)
g = run(["git", "diff", "--name-only"])
ALLOWED = {"scripts/burn_report.py", "scripts/crate_new.py", "scripts/dispatch.py",
           "experiments/breadth/run/burn_log.jsonl"}
touched = [l for l in g.stdout.splitlines() if l.strip()
           and l not in ALLOWED and not l.startswith("experiments/breadth/crates/")]
report("diff_bound", not touched, ",".join(touched))

score = sum(1 for t in ("X1_vendor_filter", "X2_crate_list", "X3_dispatch_dry_run")
            if results.get(t))
print(f"ARM SCORE: {score}/3" + ("" if results.get("diff_bound") else " (DIFF BOUND VIOLATED)"))
sys.exit(0)
