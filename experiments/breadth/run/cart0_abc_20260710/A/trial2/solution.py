def _parse(pattern):
    """Parse pattern into tokens. Raises ValueError on malformed pattern.
    Tokens: ('lit', ch), ('any',), ('one',), ('star',), ('class', negated, frozenset)
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
            tokens.append(('one',))
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
                # inside a class, backslash is a literal member, no escaping
                if (i + 2 < n and pattern[i + 1] == '-'
                        and pattern[i + 2] != ']'):
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("bad range")
                    for o in range(ord(lo), ord(hi) + 1):
                        members.add(chr(o))
                    i += 3
                else:
                    members.add(ch)
                    i += 1
            if not closed:
                raise ValueError("unclosed class")
            tokens.append(('class', negated, frozenset(members)))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word):
    ti = wi = 0
    star = None  # (token index after star, word index)
    while True:
        if ti < len(tokens):
            t = tokens[ti]
            if t[0] == 'star':
                star = (ti + 1, wi)
                ti += 1
                continue
            if wi < len(word):
                ch = word[wi]
                ok = ((t[0] == 'one') or
                      (t[0] == 'lit' and t[1] == ch) or
                      (t[0] == 'class' and ((ch in t[2]) != t[1])))
                if ok:
                    ti += 1
                    wi += 1
                    continue
        else:
            if wi == len(word):
                return True
        if star is not None and star[1] < len(word):
            star = (star[0], star[1] + 1)
            ti, wi = star
            continue
        return False


def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)
    return sum(1 for w in words if _match(tokens, w))
