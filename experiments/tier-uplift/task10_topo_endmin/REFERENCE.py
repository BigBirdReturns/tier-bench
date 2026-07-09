# Acceptance artifact: a correct submission (must PASS).
#
# Derivation: the objective fixes positions from the END, so build the schedule
# backward. The job placed last must have no outgoing constraint into the
# still-unplaced set (else it would have to precede something after it); to make
# the last job smallest, take the smallest such job — and the same argument
# applies recursively for each earlier position. Reverse the placements at the
# end. If at any step no such job exists, the remaining jobs are cyclic -> None.


def order(n, edges):
    out = {i: set() for i in range(1, n + 1)}
    for a, b in edges:
        if a == b:
            return None
        out[a].add(b)
    placed, remaining = [], set(range(1, n + 1))
    while remaining:
        sinks = [v for v in remaining if not (out[v] & remaining)]
        if not sinks:
            return None
        v = min(sinks)
        placed.append(v)
        remaining.discard(v)
    placed.reverse()
    return placed
