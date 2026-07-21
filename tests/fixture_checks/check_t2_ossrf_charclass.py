"""External acceptance for t2_ossrf_fnmatch_charclass.

Lives outside the work item's writable scope (which is input.py alone), so the
hidden grader and this wrapper are neither visible to nor writable by the hands
model. Prints the grader's SCORE line so partial credit survives a rejection.
"""
from pathlib import Path
import subprocess
import sys

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "t2_ossrf_fnmatch_charclass"
CANDIDATE = FIXTURE / "input.py"
GRADER = FIXTURE / "hidden_tests.py"

if not CANDIDATE.is_file():
    raise SystemExit("FAIL: candidate input.py is missing")
if not GRADER.is_file():
    raise SystemExit("FAIL: hidden grader is missing")

source = CANDIDATE.read_text(encoding="utf-8")
if "def translate_charclass" not in source:
    raise SystemExit("FAIL: candidate no longer defines translate_charclass")

result = subprocess.run(
    [sys.executable, "-B", "hidden_tests.py"],
    cwd=FIXTURE,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
