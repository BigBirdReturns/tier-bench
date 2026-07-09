#!/usr/bin/env python3
"""Hidden tests for t_novel_03 (derivation: build the schedule from the END).

PASS (exit 0) iff the candidate's `order(n, edges)` matches the brute-force
reference on every vector below. The reference is computed at grade time by
enumerating all permutations (every vector keeps n <= 7), so the expected
answers cannot drift from the objective's definition.

ANSWER KEY (private). The objective — minimize the job sequence read from the
END, position by position — is NOT solved by the pattern-matched recipe for
"lexicographically smallest topological order" (forward Kahn + min-heap), nor
by its mirror "emit the largest available source first so small jobs sink to
the end". The correct derivation builds the schedule BACKWARD: repeatedly take
the smallest job with no outgoing constraint into the still-unplaced set, place
it last, and reverse at the end. Forward greedy of either polarity commits
early and cannot see which jobs the constraints force away from the tail:
on n=4, edges=[(1,4)], largest-source-first yields [3,2,1,4] (job 4 dead last)
while the true answer is [1,4,3,2]. Verified: backward-smallest-sink equals
the permutation brute force on all 4096 graphs over n=4 and all <=4-edge
graphs over n=5; largest-source-first is wrong on 51 of the n=4 graphs.
Vectors 1-4 are the visible-spec shapes (both naive polarities survive them);
the rest are the discriminating set.
"""
import importlib.util
import sys
from itertools import permutations

# (n, edges) — expected answers computed by brute force at grade time
VECTORS = [
    (3, [(3, 1)]),                                # spec's worked example
    (3, [(1, 2), (2, 3)]),                        # chain
    (3, [(1, 2), (2, 3), (3, 1)]),                # cycle -> None
    (1, []),                                      # singleton
    (3, []),                                      # unconstrained
    (4, [(1, 4)]),                                # forward-greedy killer
    (4, [(2, 1), (3, 1), (4, 1)]),                # shared sink
    (5, [(1, 3), (4, 2), (4, 5)]),
    (5, [(5, 2), (5, 1), (3, 4)]),
    (6, [(1, 4), (2, 4), (6, 3), (6, 5), (5, 3)]),
    (6, [(4, 1), (4, 2), (4, 3)]),
    (2, [(2, 2)]),                                # self-loop -> None
    (3, [(3, 1), (3, 1)]),                        # duplicate edges
    (7, [(1, 5), (2, 6), (3, 7), (1, 6)]),
]


def brute(n, edges):
    best = None
    for p in permutations(range(1, n + 1)):
        pos = {v: i for i, v in enumerate(p)}
        if all(a != b and pos[a] < pos[b] for a, b in edges):
            key = tuple(reversed(p))
            if best is None or key < best[0]:
                best = (key, list(p))
    return best[1] if best else None


def main(argv):
    if len(argv) != 2:
        print("usage: python <this file> <candidate-module.py>")
        return 2
    try:
        spec = importlib.util.spec_from_file_location("candidate", argv[1])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: candidate module failed to import: {e!r}")
        return 1
    fn = getattr(mod, "order", None)
    if not callable(fn):
        print("FAIL: candidate defines no callable order()")
        return 1
    wrong = []
    for idx, (n, edges) in enumerate(VECTORS, 1):
        exp = brute(n, edges)
        try:
            got = fn(n, [tuple(e) for e in edges])
        except Exception as e:  # noqa: BLE001
            wrong.append((idx, n, edges, f"raised {type(e).__name__}", exp))
            continue
        norm = list(got) if got is not None else None
        if norm != exp:
            wrong.append((idx, n, edges, f"returned {norm!r}", exp))
    if not wrong:
        print(f"PASS: all {len(VECTORS)} vectors correct")
        return 0
    print(f"FAIL: {len(wrong)}/{len(VECTORS)} vectors wrong:")
    for idx, n, edges, why, exp in wrong:
        print(f"  #{idx} order({n}, {edges!r}): {why}, expected {exp!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
