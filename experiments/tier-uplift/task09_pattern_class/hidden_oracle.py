#!/usr/bin/env python3
"""Hidden oracle for t_novel_02 (rule-boundary knot: degenerate range).

PASS (exit 0) iff the candidate's `match(pattern, s)` agrees with the reference
semantics on every vector below. An exception from the candidate counts as a
wrong answer on that vector.

ANSWER KEY (private). The knot: an inverted range like `[7-2]` is syntactically
well-formed (the spec guarantees no pattern ever needs rejecting) and its
semantics follow strictly from the one stated rule — "matches a digit d such
that a <= d <= b". No digit satisfies 7 <= d <= 2, so the atom matches nothing
and any pattern requiring it to consume a digit matches no string at all. The
plausible failure is judging it malformed (raise) or "helpfully" swapping the
endpoints — the same malformed-vs-unsatisfiable judgment class as the measured
task02 escape-in-class residue, on a fresh construct. Vectors 17-23 are the
knot; 1-16 and 24 are settled coverage a correct-but-ordinary implementation
passes. The oracle self-checks its embedded reference against the expected
column before grading and refuses to grade if they ever disagree — a broken
grader must mint neither PASS nor FAIL.
"""
import importlib.util
import sys
from functools import lru_cache

# (pattern, s, expected)
VECTORS = [
    ("123", "123", True), ("123", "124", False), ("?", "7", True), ("?", "", False),
    ("*", "", True), ("*", "0451", True), ("1*9", "19", True), ("1*9", "10009", True),
    ("1*9", "91", False), ("[2-7]", "5", True), ("[2-7]", "8", False),
    ("[5-5]", "5", True), ("[5-5]", "4", False), ("?[0-9]*", "42", True),
    ("*[0-4]", "39", False), ("*[0-4]*", "39", True),
    ("[7-2]", "5", False), ("[7-2]", "2", False), ("[7-2]", "7", False),
    ("[9-0]", "", False), ("*[7-2]", "123", False), ("*[7-2]*", "0123456789", False),
    ("1[8-3]9", "19", False), ("[3-3]*", "3", True),
]


def _parse(pattern):
    atoms, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "[":
            atoms.append(("range", pattern[i + 1], pattern[i + 3]))
            i += 5
        elif c == "?":
            atoms.append(("any",))
            i += 1
        elif c == "*":
            atoms.append(("star",))
            i += 1
        else:
            atoms.append(("lit", c))
            i += 1
    return atoms


def reference_match(pattern, s):
    atoms = _parse(pattern)

    @lru_cache(maxsize=None)
    def go(ai, si):
        if ai == len(atoms):
            return si == len(s)
        a = atoms[ai]
        if a[0] == "star":
            return any(go(ai + 1, j) for j in range(si, len(s) + 1))
        if si >= len(s):
            return False
        ch = s[si]
        if a[0] == "lit":
            okc = ch == a[1]
        elif a[0] == "any":
            okc = True
        else:
            okc = a[1] <= ch <= a[2]
        return okc and go(ai + 1, si + 1)

    return go(0, 0)


def main(argv):
    # Self-check: the embedded reference must reproduce the expected column.
    for p, s, exp in VECTORS:
        if reference_match(p, s) != exp:
            print(f"GRADER BROKEN: embedded reference disagrees with expected on {(p, s)!r}")
            return 3
    if len(argv) != 2:
        print("usage: python <this oracle> <candidate-module.py>")
        return 2
    try:
        spec = importlib.util.spec_from_file_location("candidate", argv[1])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: candidate module failed to import: {e!r}")
        return 1
    fn = getattr(mod, "match", None)
    if not callable(fn):
        print("FAIL: candidate defines no callable match()")
        return 1
    wrong = []
    for idx, (p, s, exp) in enumerate(VECTORS, 1):
        try:
            got = bool(fn(p, s))
        except Exception as e:  # noqa: BLE001
            wrong.append((idx, p, s, f"raised {type(e).__name__}"))
            continue
        if got != exp:
            wrong.append((idx, p, s, f"returned {got}, expected {exp}"))
    if not wrong:
        print(f"PASS: all {len(VECTORS)} vectors correct")
        return 0
    print(f"FAIL: {len(wrong)}/{len(VECTORS)} vectors wrong:")
    for idx, p, s, why in wrong:
        print(f"  #{idx} match({p!r}, {s!r}): {why}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
