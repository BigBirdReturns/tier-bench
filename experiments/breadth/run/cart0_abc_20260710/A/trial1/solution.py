"""Wildcard pattern matching: count words matched entirely by pattern."""


def _parse(pattern: str):
    """Tokenize pattern. Raises ValueError on malformed pattern.

    Tokens: ('star',), ('q',), ('lit', ch), ('class', frozenset, negated)
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
            tokens.append(('q',))
            i += 1
        elif c == '[':
            i += 1
            negated = False
            if i < n and pattern[i] == '!':
                negated = True
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
                # Inside a class, backslash is a literal member, not escape.
                # Range: ch '-' end, where '-' is not at the edge.
                if (i + 2 < n and pattern[i + 1] == '-'
                        and pattern[i + 2] != ']'):
                    low, high = ch, pattern[i + 2]
                    if ord(low) > ord(high):
                        raise ValueError("malformed range: low > high")
                    for code in range(ord(low), ord(high) + 1):
                        members.add(chr(code))
                    i += 3
                else:
                    members.add(ch)
                    i += 1
            if not closed:
                raise ValueError("unclosed character class")
            tokens.append(('class', frozenset(members), negated))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word):
    """Iterative wildcard match (greedy star with backtracking)."""
    ti = wi = 0
    star_ti = -1
    star_wi = 0
    nt, nw = len(tokens), len(word)
    while wi < nw:
        if ti < nt:
            tok = tokens[ti]
            kind = tok[0]
            if kind == 'star':
                star_ti = ti
                star_wi = wi
                ti += 1
                continue
            if kind == 'q':
                ti += 1
                wi += 1
                continue
            if kind == 'lit':
                if tok[1] == word[wi]:
                    ti += 1
                    wi += 1
                    continue
            elif kind == 'class':
                inside = word[wi] in tok[1]
                if inside != tok[2]:
                    ti += 1
                    wi += 1
                    continue
        if star_ti >= 0:
            star_wi += 1
            wi = star_wi
            ti = star_ti + 1
        else:
            return False
    while ti < nt and tokens[ti][0] == 'star':
        ti += 1
    return ti == nt


def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)
    return sum(1 for w in words if _match(tokens, w))
