#!/usr/bin/env python3
"""Objective grader for task 06 (novel-reasoning probe).

The bug is conceptual (a plausible greedy + single-swap repair that is not always
optimal). There is no line to flag — the only way to "find" it is to produce an
input on which the code is provably wrong. So grading is a **counterexample
check**: given a candidate's claimed `(items, k)`, run the subject against a
brute-force reference; the candidate found the bug iff subject != reference on a
valid input.

    python grader.py --check "items=[(1,1),(1,1),(1,0),(1,0)]; k=2"   # verify one counterexample
    python grader.py --stats                                          # subtlety of the flaw
"""
import argparse
import sys
from itertools import combinations, product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from subject import select


def reference(items, k):
    """Correct: brute-force the exact objective in the spec."""
    n = len(items)
    if k < 0 or k > n:
        return None
    best = None
    for combo in combinations(range(n), k):
        if sum(items[i][1] for i in combo) % 3 == 0:
            v = sum(items[i][0] for i in combo)
            if best is None or v > best:
                best = v
    return best


def check(items, k):
    """Return (is_counterexample, subject_out, reference_out)."""
    s, r = select(items, k), reference(items, k)
    return (s != r, s, r)


def stats():
    diffs = tot = 0
    example = None
    for n in range(3, 6):
        for k in range(1, n + 1):
            for vals in product(range(1, 5), repeat=n):
                for wts in product(range(0, 4), repeat=n):
                    items = list(zip(vals, wts))
                    tot += 1
                    if select(items, k) != reference(items, k):
                        diffs += 1
                        if example is None:
                            example = (items, k)
        if tot > 300000:
            break
    print(f"subject differs from reference on {diffs}/{tot} = {100*diffs/tot:.2f}% of small cases")
    print(f"first counterexample: {example}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", help='e.g. "items=[(3,1),(2,2)]; k=1"')
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        stats()
    if a.check:
        ns = {}
        exec(a.check, ns)  # trusted: our own extracted counterexample
        items, k = ns["items"], ns["k"]
        is_ce, s, r = check(items, k)
        print(f"items={items} k={k}")
        print(f"  subject   = {s}")
        print(f"  reference = {r}")
        print(f"  COUNTEREXAMPLE: {is_ce}")
