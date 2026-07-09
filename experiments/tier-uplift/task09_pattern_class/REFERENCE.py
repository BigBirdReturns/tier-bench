# Acceptance artifact: a correct submission (must PASS).
#
# Applies the stated range rule unconditionally: `[a-b]` matches d iff
# a <= d <= b. When a > b no digit qualifies, so the atom is unsatisfiable and
# any pattern requiring it matches nothing — valid syntax, empty semantics.
from functools import lru_cache


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
