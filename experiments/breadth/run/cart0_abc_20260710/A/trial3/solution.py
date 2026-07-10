"""Wildcard pattern matching per spec.md."""


def _parse(pattern: str):
    """Tokenize pattern. Tokens:
    ('star',), ('any',), ('lit', ch), ('class', frozenset, negated)
    Raises ValueError on malformed patterns.
    """
    tokens = []
    i = 0
    n = len(pattern)
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
            tokens.append(('any',))
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
                # inside a class, backslash is a literal member (spec rule)
                # range: ch '-' next, where '-' not at edge
                if (i + 2 < n and pattern[i + 1] == '-'
                        and pattern[i + 2] != ']'):
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range: low > high")
                    for o in range(ord(lo), ord(hi) + 1):
                        members.add(chr(o))
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


def _tok_match(tok, ch):
    kind = tok[0]
    if kind == 'any':
        return True
    if kind == 'lit':
        return ch == tok[1]
    if kind == 'class':
        return (ch in tok[1]) != tok[2]
    return False


def _match(tokens, word):
    """Iterative wildcard match with star backtracking."""
    ti = wi = 0
    star_ti = -1
    star_wi = 0
    nt, nw = len(tokens), len(word)
    while wi < nw:
        if ti < nt and tokens[ti][0] == 'star':
            star_ti = ti
            star_wi = wi
            ti += 1
        elif ti < nt and _tok_match(tokens[ti], word[wi]):
            ti += 1
            wi += 1
        elif star_ti != -1:
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
