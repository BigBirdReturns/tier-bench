#!/usr/bin/env python3
"""Hidden grader for t_novel_01 (counterexample construction, task06-shape).

Judges a candidate module's claimed counterexample against the subject and a
brute-force reference. PASS (exit 0) iff the candidate's `counterexample()`
returns a domain-valid `(xs, k)` on which `pick(xs, k) != reference(xs, k)`.

ANSWER KEY (private). The subject's flaw profile, verified by exhaustive sweep
(values<=3, n<=5: 235/7736 cells disagree, ~3%; minimal disagreeing length 4):
  - The greedy can reach k with a suboptimal pair when a high-value pick's
    adjacency shadows the true optimum (smallest case shape: [0,1,2,2], k=2 —
    greedy takes index 2 then index 0 for total 2; optimum is indices 1,3 = 3).
  - The repair pass only fires when greedy falls SHORT of k, and a single
    exchange cannot fix arrangements that need two displacements: [4,5,4,5,4],
    k=3 — greedy takes the two 5s (indices 1,3), blocking everything; every
    single exchange still tops out at 2 picks, so pick returns None; the true
    answer is indices 0,2,4 = 12.
The textbook trap [4,5,4], k=2 is HANDLED by the repair (returns 8, correct) —
a pattern-matched guess of that shape fails this grader; verified explicitly.

The subject below is embedded verbatim (kept identical to subject.py/spec.md)
so grading never reads any solver-facing file.
"""
import importlib.util
import sys
from itertools import combinations

MAX_LEN, MAX_VAL = 12, 50


def pick(xs, k):
    n = len(xs)
    order = sorted(range(n), key=lambda i: (-xs[i], i))
    chosen = []

    def ok(sel, j):
        return all(abs(j - c) > 1 for c in sel)

    for i in order:
        if len(chosen) == k:
            break
        if ok(chosen, i):
            chosen.append(i)
    if len(chosen) == k:
        return sum(xs[i] for i in chosen)
    best = None
    for c in list(chosen):
        for u in range(n):
            if u in chosen:
                continue
            trial = [i for i in chosen if i != c]
            if not ok(trial, u):
                continue
            trial.append(u)
            for i in order:
                if len(trial) == k:
                    break
                if i not in trial and ok(trial, i):
                    trial.append(i)
            if len(trial) == k:
                s = sum(xs[i] for i in trial)
                if best is None or s > best:
                    best = s
    return best


def reference(xs, k):
    n = len(xs)
    if k < 0 or k > n:
        return None
    best = None
    for combo in combinations(range(n), k):
        if all(b - a > 1 for a, b in zip(combo, combo[1:])):
            v = sum(xs[i] for i in combo)
            if best is None or v > best:
                best = v
    return best


def main(argv):
    if len(argv) != 2:
        print("usage: python <this grader> <candidate-module.py>")
        return 2
    try:
        spec = importlib.util.spec_from_file_location("candidate", argv[1])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 — any import failure is a clean FAIL
        print(f"FAIL: candidate module failed to import: {e!r}")
        return 1
    fn = getattr(mod, "counterexample", None)
    if not callable(fn):
        print("FAIL: candidate defines no callable counterexample()")
        return 1
    try:
        cx = fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: counterexample() raised: {e!r}")
        return 1
    try:
        xs, k = cx
        xs = list(xs)
        if not (1 <= len(xs) <= MAX_LEN):
            raise ValueError("length out of bounds")
        if not all(isinstance(v, int) and 0 <= v <= MAX_VAL for v in xs):
            raise ValueError("value out of bounds")
        if not (isinstance(k, int) and 0 <= k <= len(xs)):
            raise ValueError("k out of bounds")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: not a domain-valid (xs, k): {cx!r} ({e})")
        return 1
    s, r = pick(xs, k), reference(xs, k)
    if s != r:
        print(f"PASS: pick({xs!r}, {k!r}) = {s!r} but the correct answer is {r!r}")
        return 0
    print(f"FAIL: pick agrees with the reference on ({xs!r}, {k!r}) (both {r!r}) "
          "— not a counterexample")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
