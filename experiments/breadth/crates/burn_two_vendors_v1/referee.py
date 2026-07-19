"""FROZEN REFEREE — burn_two_vendors_v1. Deterministic; the only pass criterion.
Run from repo root: python experiments/breadth/crates/burn_two_vendors_v1/referee.py
"""
import json
import subprocess
import sys

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" — " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


def run(args):
    return subprocess.run([sys.executable, "scripts/burn_report.py"] + args,
                          capture_output=True, text=True, timeout=120)

r = run(["--json"])
check("json_exit0", r.returncode == 0, r.stderr[-200:] if r.returncode else "")
try:
    d = json.loads(r.stdout)
    v = d.get("vendors", {})
    check("vendors_key", isinstance(v, dict))
    for vendor in ("anthropic", "openai"):
        vd = v.get(vendor, {})
        check(f"vendor_{vendor}",
              isinstance(vd.get("total_usd"), (int, float)) and isinstance(vd.get("sessions"), int))
    check("anthropic_nonzero", v.get("anthropic", {}).get("sessions", 0) > 0,
          "existing sidecars must still be counted")
    # REFEREE CORRECTION (v2, 2026-07-18): haiku attempt 1 passed v1's type checks
    # while reporting openai total_usd ≈ $1,000,974 — a missing per-million-token
    # divisor. v1 had no sanity bound; adjudication caught it at the desk. Bound:
    # no local CLI tank plausibly exceeds $10k.
    for vendor in ("anthropic", "openai"):
        t = v.get(vendor, {}).get("total_usd", 0)
        check(f"sane_total_{vendor}", 0 <= t < 10_000, f"${t:,.2f}")
except Exception as e:  # noqa: BLE001
    check("json_parses", False, str(e))

r = run(["--top", "3"])
check("top_still_works", r.returncode == 0)

r = run(["--selftest"])
check("selftest", r.returncode == 0 and "SELFTEST OK" in r.stdout, r.stdout[-200:])

g = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
touched = [l for l in g.stdout.splitlines() if l.strip()]
# Sibling crates run concurrently in this worktree; their targets are not contamination.
ALLOWED = {"scripts/burn_report.py", "experiments/breadth/run/burn_log.jsonl",
           "tests/test_tier_pilot_admin.py"}
bad = [t for t in touched if t not in ALLOWED
       and not t.startswith("experiments/breadth/crates/")]
check("only_burn_report_touched", not bad, ",".join(bad))

print("REFEREE:", "PASS" if not FAILS else "FAIL " + ",".join(FAILS))
sys.exit(0 if not FAILS else 1)
