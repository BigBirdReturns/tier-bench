def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)
    return sum(1 for w in words if _match(tokens, w))


def _parse(pattern: str):
    tokens = []  # ('lit', ch) | ('star',) | ('q',) | ('cls', frozenset, negated)
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
            members = []  # raw chars, inside class backslash is literal
            # ']' literal if first member
            if i < n and pattern[i] == ']':
                members.append(']')
                i += 1
            while i < n and pattern[i] != ']':
                members.append(pattern[i])
                i += 1
            if i >= n:
                raise ValueError("unclosed character class")
            i += 1  # skip ']'
            chars = set()
            j, m = 0, len(members)
            while j < m:
                # range: X-Y where '-' is not at either edge
                if (j + 2 < m or (j + 2 == m and True)) and j + 1 < m and members[j + 1] == '-' and j + 2 < m:
                    lo, hi = members[j], members[j + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range")
                    for code in range(ord(lo), ord(hi) + 1):
                        chars.add(chr(code))
                    j += 3
                else:
                    chars.add(members[j])
                    j += 1
            tokens.append(('cls', frozenset(chars), negated))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word):
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def rec(ti, wi):
        if ti == len(tokens):
            return wi == len(word)
        t = tokens[ti]
        if t[0] == 'star':
            for k in range(wi, len(word) + 1):
                if rec(ti + 1, k):
                    return True
            return False
        if wi >= len(word):
            return False
        ch = word[wi]
        if t[0] == 'q':
            ok = True
        elif t[0] == 'lit':
            ok = ch == t[1]
        else:
            ok = (ch in t[1]) != t[2]
        return ok and rec(ti + 1, wi + 1)

    return rec(0, 0)
