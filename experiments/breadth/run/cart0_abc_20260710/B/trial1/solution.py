def _parse(pattern: str):
    """Parse pattern into tokens. Raises ValueError on malformed patterns.

    Tokens: ('lit', ch), ('any1',), ('star',), ('class', negated, frozenset)
    Rule commitment: inside a character class, backslash is a literal member
    (and legal range endpoint), never an escape. Outside, it escapes.
    """
    tokens = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '*':
            tokens.append(('star',))
            i += 1
        elif c == '?':
            tokens.append(('any1',))
            i += 1
        elif c == '[':
            i += 1
            neg = False
            if i < n and pattern[i] == '!':
                neg = True
                i += 1
            members = set()
            first = True
            closed = False
            while i < n:
                ch = pattern[i]
                if ch == ']' and not first:
                    closed = True
                    i += 1
                    break
                first = False
                # range? need a '-' next that is not at the closing edge
                if (i + 2 < n and pattern[i + 1] == '-' and
                        pattern[i + 2] != ']'):
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("bad range")
                    for code in range(ord(lo), ord(hi) + 1):
                        members.add(chr(code))
                    i += 3
                else:
                    members.add(ch)
                    i += 1
            if not closed:
                raise ValueError("unclosed class")
            tokens.append(('class', neg, frozenset(members)))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word):
    # iterative with star backtracking
    ti = wi = 0
    star_ti = star_wi = -1
    n, m = len(tokens), len(word)
    while wi < m:
        if ti < n:
            t = tokens[ti]
            if t[0] == 'star':
                star_ti, star_wi = ti, wi
                ti += 1
                continue
            ok = False
            if t[0] == 'lit':
                ok = word[wi] == t[1]
            elif t[0] == 'any1':
                ok = True
            else:  # class
                ok = (word[wi] in t[2]) != t[1]
            if ok:
                ti += 1
                wi += 1
                continue
        if star_ti >= 0:
            star_wi += 1
            wi = star_wi
            ti = star_ti + 1
        else:
            return False
    while ti < n and tokens[ti][0] == 'star':
        ti += 1
    return ti == n


def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)
    return sum(1 for w in words if _match(tokens, w))
