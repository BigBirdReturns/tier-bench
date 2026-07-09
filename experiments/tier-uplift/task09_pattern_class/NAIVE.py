# Acceptance artifact: the plausible-but-wrong submission (must FAIL).
#
# A defensively-written matcher: parses the pattern up front and VALIDATES each
# range, rejecting inverted endpoints as malformed input. The engine is
# otherwise correct — this passes every vector whose ranges are ordered. The
# flaw is the judgment call, not the algorithm: the spec guarantees patterns
# never need rejecting, and the stated rule already gives an inverted range a
# meaning (it matches no digit). Treating the degenerate case as an error
# instead of applying the rule is the malformed-vs-unsatisfiable trap.
from functools import lru_cache


def _parse(pattern):
    atoms, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "[":
            lo, hi = pattern[i + 1], pattern[i + 3]
            if lo > hi:
                raise ValueError(f"invalid range [{lo}-{hi}]")
            atoms.append(("range", lo, hi))
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


def match(pattern, s):
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
