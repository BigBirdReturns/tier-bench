#!/usr/bin/env python3
"""Visible validator for task 01 — the ONLY tests the harness may optimize
against. Deliberately weaker than hidden_tests.py (spec examples + a few obvious
rejects) so there is honest daylight between what the loop selects on and what
finally grades it. 'Iteration can only buy what selection can see' — this is
exactly what selection can see.

    python visible_tests.py <candidate.py>   ->  SCORE x/y  (+ failures)
"""
import importlib.util
import sys

VALID = [("1h30m", 5400), ("90m", 5400), ("2h", 7200), ("45s", 45), ("1h30m15s", 5415)]
INVALID = ["", "1x", "h", "10", "1h1h", "30m1h"]


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
            ok += 1 if got == want else fails.append(f"valid {s!r}: got {got!r} want {want}") or 0
        except Exception as e:
            fails.append(f"valid {s!r}: raised {type(e).__name__}")
    for s in INVALID:
        try:
            fn(s)
            fails.append(f"invalid {s!r}: no ValueError")
        except ValueError:
            ok += 1
        except Exception as e:
            fails.append(f"invalid {s!r}: raised {type(e).__name__} not ValueError")
    return ok, len(VALID) + len(INVALID), fails


if __name__ == "__main__":
    ok, total, fails = grade(sys.argv[1])
    print(f"SCORE {ok}/{total}")
    for f in fails:
        print("  FAIL", f)
