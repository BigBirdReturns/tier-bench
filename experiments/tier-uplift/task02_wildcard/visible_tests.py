#!/usr/bin/env python3
"""Visible validator for task 02 — the ONLY cases the harness may select against.
Curated + hand-verified, far smaller than the 10k-case hidden oracle. The gap
between this and hidden_oracle.py is the point: the loop can only buy what these
can see.

    python visible_tests.py <candidate.py>   ->  SCORE ok/total (+ failures)
"""
import importlib.util
import sys

# (pattern, text, expected_bool) — valid cases
VALID = [
    ("*", "", True), ("*", "abc", True), ("a*c", "abbbc", True), ("a*c", "abbb", False),
    ("?", "a", True), ("?", "", False), ("a?c", "abc", True), ("a?c", "ac", False),
    ("[a-c]", "b", True), ("[a-c]", "d", False), ("[!a-c]", "d", True), ("[!a-c]", "b", False),
    ("[]a]", "]", True), ("[]a]", "a", True), (r"\*", "*", True), (r"\*", "a", False),
    ("a[b-d]*z", "acxyz", True), ("*.txt", "a.txt", True), ("*.txt", "a.txtx", False),
    ("", "", True), ("", "a", False), ("a*b*c", "axbyc", True), ("a*b*c", "axbyd", False),
]
# patterns that must raise ValueError
INVALID = ["[abc", "a\\", "[z-a]"]


def load(path):
    spec = importlib.util.spec_from_file_location("cand", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wildcard_match


def grade(path):
    try:
        fn = load(path)
    except Exception as e:
        return 0, len(VALID) + len(INVALID), [f"LOAD ERROR: {e}"]
    ok, fails = 0, []
    for p, t, want in VALID:
        try:
            got = fn(p, t)
            ok += 1 if bool(got) == want else fails.append(f"({p!r},{t!r}) got {got!r} want {want}") or 0
        except Exception as e:
            fails.append(f"({p!r},{t!r}) raised {type(e).__name__}")
    for p in INVALID:
        try:
            fn(p, "x"); fails.append(f"({p!r}) no ValueError")
        except ValueError:
            ok += 1
        except Exception as e:
            fails.append(f"({p!r}) raised {type(e).__name__} not ValueError")
    return ok, len(VALID) + len(INVALID), fails


if __name__ == "__main__":
    ok, total, fails = grade(sys.argv[1])
    print(f"SCORE {ok}/{total}")
    for f in fails:
        print("  FAIL", f)
