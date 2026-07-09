# Acceptance artifact: the plausible-but-wrong submission (must FAIL).
#
# The intuitive forward greedy: "emit the largest available job first, so the
# small ones sink to the end of the schedule." It reproduces the spec's worked
# example, the chain, the cycle case, and the unconstrained case — and it is
# wrong, because committing from the FRONT cannot see which jobs the
# constraints will force toward the tail later.


def order(n, edges):
    inc = {i: set() for i in range(1, n + 1)}
    for a, b in edges:
        inc[b].add(a)
    res, remaining = [], set(range(1, n + 1))
    while remaining:
        sources = [v for v in remaining if not (inc[v] & remaining)]
        if not sources:
            return None
        v = max(sources)
        res.append(v)
        remaining.discard(v)
    return res
