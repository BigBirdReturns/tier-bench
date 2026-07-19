"""FROZEN REFEREE — admin_question_test_v1. Deterministic; the only pass criterion.
Run from repo root: python experiments/breadth/crates/admin_question_test_v1/referee.py
"""
import re
import subprocess
import sys
from pathlib import Path

FAILS = []
TESTFILE = Path("tests/test_tier_pilot_admin.py")
NAME = "test_arm_c_question_requires_exact_intervention_interval"


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" — " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


src = TESTFILE.read_text(encoding="utf-8")

# 1. Exactly one definition of the witness, no unreachable second body
check("single_def", len(re.findall(rf"^def {NAME}\(", src, re.M)) == 1)

# 2. Registered in main(): the bare name appears as a call/reference outside its def line
main_match = re.search(r"^def main\(\).*?(?=^def |\Z)", src, re.M | re.S)
check("registered_in_main", bool(main_match) and NAME in main_match.group(0))

# 3. The full manual suite passes
r = subprocess.run([sys.executable, str(TESTFILE)], capture_output=True, text=True, timeout=600)
check("suite_green", r.returncode == 0, (r.stdout + r.stderr)[-300:])

# 4. Only the test file was modified
g = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
# Sibling crates run concurrently in this worktree; their targets are not contamination.
ALLOWED = {"experiments/breadth/run/burn_log.jsonl", "scripts/burn_report.py"}
touched = [l for l in g.stdout.splitlines() if l.strip()
           and l not in ALLOWED
           and not l.startswith("experiments/breadth/crates/")]
check("only_testfile_touched", touched == [str(TESTFILE).replace("\\", "/")] or touched == [],
      ",".join(touched))

print("REFEREE:", "PASS" if not FAILS else "FAIL " + ",".join(FAILS))
sys.exit(0 if not FAILS else 1)
