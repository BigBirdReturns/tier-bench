def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)  # parse first: malformed pattern always raises
    return sum(1 for w in words if _match(tokens, w))


def _parse(pattern: str):
    """Tokenize pattern into a list of tokens:
       ('star',) | ('any',) | ('lit', ch) | ('class', frozenset, negated)"""
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
            # collect raw members; ']' as first member is literal;
            # inside a class, backslash is a literal member, NOT an escape
            members = []
            if i < n and pattern[i] == ']':
                members.append(']')
                i += 1
            while i < n and pattern[i] != ']':
                members.append(pattern[i])
                i += 1
            if i >= n:
                raise ValueError("unclosed character class")
            i += 1  # consume closing ']'
            # resolve ranges: '-' literal at edges, range in the middle
            chars = set()
            j = 0
            m = len(members)
            while j < m:
                if members[j] == '-' and 0 < j < m - 1:
                    # can't happen: '-' as range operator is consumed below
                    chars.add('-')
                    j += 1
                elif j + 2 < m or (j + 2 == m and False):
                    j += 0  # fallthrough handled below
                    if members[j + 1] == '-' if j + 2 < m else False:
                        pass
                    break
                else:
                    break
            # (rewritten cleanly below)
            chars = set()
            j = 0
            while j < m:
                if j + 2 < m + 1 and j + 1 < m and members[j + 1] == '-' and j + 2 < m:
                    lo, hi = members[j], members[j + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("invalid range in character class")
                    for code in range(ord(lo), ord(hi) + 1):
                        chars.add(chr(code))
                    j += 3
                else:
                    chars.add(members[j])
                    j += 1
            tokens.append(('class', frozenset(chars), negated))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _token_matches_char(tok, ch: str) -> bool:
    kind = tok[0]
    if kind == 'any':
        return True
    if kind == 'lit':
        return ch == tok[1]
    if kind == 'class':
        _, chars, negated = tok
        inside = ch in chars
        return (not inside) if negated else inside
    return False  # 'star' never consumes via this path


def _match(tokens, word: str) -> bool:
    """Iterative backtracking (classic two-pointer with star bookmark)."""
    ti = wi = 0
    star_ti = -1   # token index just after the most recent '*'
    star_wi = 0    # word position where that '*' started consuming
    nt, nw = len(tokens), len(word)
    while wi < nw:
        if ti < nt and tokens[ti][0] == 'star':
            star_ti = ti + 1
            star_wi = wi
            ti += 1
        elif ti < nt and tokens[ti][0] != 'star' and _token_matches_char(tokens[ti], word[wi]):
            ti += 1
            wi += 1
        elif star_ti != -1:
            # backtrack: let the last '*' consume one more character
            star_wi += 1
            wi = star_wi
            ti = star_ti
        else:
            return False
    # word exhausted: remaining tokens must all be '*'
    while ti < nt and tokens[ti][0] == 'star':
        ti += 1
    return ti == nt
