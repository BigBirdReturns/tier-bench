def _parse(pattern: str):
    """Compile pattern into a token list; raise ValueError on malformed input."""
    tokens = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            # Escape outside a class: next char is literal; trailing '\' is malformed.
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '*':
            if not tokens or tokens[-1] != ('star',):  # collapse runs of '*'
                tokens.append(('star',))
            i += 1
        elif c == '?':
            tokens.append(('any',))
            i += 1
        elif c == '[':
            i += 1
            neg = False
            if i < n and pattern[i] == '!':
                neg = True
                i += 1
            chars = set()
            ranges = []
            first = True
            closed = False
            while i < n:
                ch = pattern[i]
                if ch == ']' and not first:
                    closed = True
                    i += 1
                    break
                # ch is a member; ']' as first member is literal.
                # In-class backslash is a LITERAL, never an escape prefix.
                if i + 2 < n and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("bad range %r-%r" % (lo, hi))
                    ranges.append((lo, hi))
                    i += 3
                else:
                    # Covers literal members, '-' at either edge, and '\'.
                    chars.add(ch)
                    i += 1
                first = False
            if not closed:
                raise ValueError("unclosed character class")
            tokens.append(('class', neg, frozenset(chars), tuple(ranges)))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word: str) -> bool:
    memo = {}

    def rec(ti: int, wi: int) -> bool:
        key = (ti, wi)
        if key in memo:
            return memo[key]
        if ti == len(tokens):
            res = wi == len(word)
        else:
            tok = tokens[ti]
            kind = tok[0]
            if kind == 'star':
                # Match empty, or consume one char and stay on '*'.
                res = rec(ti + 1, wi) or (wi < len(word) and rec(ti, wi + 1))
            elif wi >= len(word):
                res = False
            elif kind == 'any':
                res = rec(ti + 1, wi + 1)
            elif kind == 'lit':
                res = tok[1] == word[wi] and rec(ti + 1, wi + 1)
            else:  # class
                _, neg, chars, ranges = tok
                ch = word[wi]
                inside = ch in chars or any(lo <= ch <= hi for lo, hi in ranges)
                res = (inside != neg) and rec(ti + 1, wi + 1)
        memo[key] = res
        return res

    return rec(0, 0)


def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)  # malformed pattern raises before any counting
    return sum(1 for w in words if _match(tokens, w))
