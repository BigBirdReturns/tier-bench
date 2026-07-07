#!/usr/bin/env python3
"""Hidden grader for task 01. Not shown to solvers. Scores a candidate file's
parse_duration against valid + invalid cases; prints pass count and failures.

    python hidden_tests.py <candidate.py>
"""
import importlib.util
import sys
from pathlib import Path

VALID = [
    ("1h30m", 5400), ("90m", 5400), ("2h", 7200), ("45s", 45),
    ("1h30m15s", 5415), ("0s", 0), ("100h", 360000), ("1h1m1s", 3661),
    ("59m59s", 3599), ("0h0m0s", 0), ("10m", 600), ("3h15s", 10815),
]
# each of these MUST raise ValueError
INVALID = [
    "", "1x", "1d", "1.5h", "1,5h", "h", "hm", "10", "1h1h", "1h2h",
    "30m1h", "15s30m", "-1h", "1h ", " 1h", "1h 30m", "1H", "1m30h",
    "s", "abc", "1h30", "30", "1hh", "m5", "1s1s", "1h0h",
]


def load(path):
    spec = importlib.util.spec_from_file_location("cand", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_duration


def grade(path):
    fails = []
    try:
        fn = load(path)
    except Exception as e:
        return 0, len(VALID) + len(INVALID), [f"LOAD ERROR: {e}"]
    ok = 0
    for s, want in VALID:
        try:
            got = fn(s)
            if got == want:
                ok += 1
            else:
                fails.append(f"valid {s!r}: got {got!r}, want {want}")
        except Exception as e:
            fails.append(f"valid {s!r}: raised {type(e).__name__}({e})")
    for s in INVALID:
        try:
            got = fn(s)
            fails.append(f"invalid {s!r}: returned {got!r}, expected ValueError")
        except ValueError:
            ok += 1
        except Exception as e:
            fails.append(f"invalid {s!r}: raised {type(e).__name__}, expected ValueError")
    return ok, len(VALID) + len(INVALID), fails


if __name__ == "__main__":
    ok, total, fails = grade(sys.argv[1])
    print(f"SCORE {ok}/{total}")
    for f in fails[:40]:
        print("  FAIL", f)
