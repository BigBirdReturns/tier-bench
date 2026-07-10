def _parse(pattern):
    toks = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == '*':
            if not toks or toks[-1] != ('*',):
                toks.append(('*',))
            i += 1
        elif c == '?':
            toks.append(('?',))
            i += 1
        elif c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            toks.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '[':
            i += 1
            neg = False
            if i < n and pattern[i] == '!':
                neg = True
                i += 1
            members = set()
            first = True
            while True:
                if i >= n:
                    raise ValueError("unclosed character class")
                ch = pattern[i]
                if ch == ']' and not first:
                    i += 1
                    break
                first = False
                # inside a class, backslash is a literal member (no escaping)
                if i + 2 < n and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range %s-%s" % (lo, hi))
                    members.update(chr(x) for x in range(ord(lo), ord(hi) + 1))
                    i += 3
                else:
                    members.add(ch)
                    i += 1
            toks.append(('cls', neg, frozenset(members)))
        else:
            toks.append(('lit', c))
            i += 1
    return toks


def _tok_matches(tok, ch):
    kind = tok[0]
    if kind == '?':
        return True
    if kind == 'lit':
        return ch == tok[1]
    if kind == 'cls':
        return (ch in tok[2]) != tok[1]
    return False


def _match(toks, s):
    # NFA-style state set: state = index into toks
    states = {0}
    m = len(toks)

    def close(st):
        # epsilon-advance over '*'
        out = set()
        stack = list(st)
        while stack:
            j = stack.pop()
            if j in out:
                continue
            out.add(j)
            if j < m and toks[j] == ('*',):
                stack.append(j + 1)
        return out

    states = close(states)
    for ch in s:
        nxt = set()
        for j in states:
            if j >= m:
                continue
            t = toks[j]
            if t == ('*',):
                nxt.add(j)  # star consumes char, stays
            elif _tok_matches(t, ch):
                nxt.add(j + 1)
        states = close(nxt)
        if not states:
            return False
    return m in states


def count_matches(pattern: str, words: list) -> int:
    toks = _parse(pattern)
    return sum(1 for w in words if _match(toks, w))
