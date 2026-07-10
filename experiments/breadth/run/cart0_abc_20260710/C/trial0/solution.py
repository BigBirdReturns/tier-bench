def _parse(pattern: str):
    """Tokenize pattern; raise ValueError on malformed input.

    Tokens: ('star',), ('any',), ('lit', ch), ('class', frozenset, negated)
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
            j = i + 1
            negated = False
            if j < n and pattern[j] == '!':
                negated = True
                j += 1
            members = set()
            first = True
            closed = False
            while j < n:
                ch = pattern[j]
                if ch == ']' and not first:
                    closed = True
                    j += 1
                    break
                # Inside a class, backslash is a literal member, not an escape.
                # Range? need '-' next, and char after '-' not the closing ']'
                if (j + 2 < n and pattern[j + 1] == '-'
                        and pattern[j + 2] != ']'):
                    lo, hi = ch, pattern[j + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range: low > high")
                    for code in range(ord(lo), ord(hi) + 1):
                        members.add(chr(code))
                    j += 3
                else:
                    members.add(ch)
                    j += 1
                first = False
            if not closed:
                raise ValueError("unclosed character class")
            tokens.append(('class', frozenset(members), negated))
            i = j
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _single_match(tok, ch) -> bool:
    kind = tok[0]
    if kind == 'any':
        return True
    if kind == 'lit':
        return tok[1] == ch
    if kind == 'class':
        return (ch in tok[1]) != tok[2]
    return False


def _match(tokens, word: str) -> bool:
    ti = wi = 0
    star_ti = -1
    star_wi = 0
    nt, nw = len(tokens), len(word)
    while wi < nw:
        if ti < nt and tokens[ti][0] == 'star':
            star_ti = ti
            star_wi = wi
            ti += 1
        elif ti < nt and _single_match(tokens[ti], word[wi]):
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
