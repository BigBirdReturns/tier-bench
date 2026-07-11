def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)
    return sum(1 for w in words if _match(tokens, w))


def _parse(pattern: str):
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            # Escape outside a class: next char is literal.
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '*':
            # Collapse consecutive stars.
            if not tokens or tokens[-1] != ('star',):
                tokens.append(('star',))
            i += 1
        elif c == '?':
            tokens.append(('any',))
            i += 1
        elif c == '[':
            i += 1
            negate = False
            if i < n and pattern[i] == '!':
                negate = True
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
                # Inside a class, backslash is a literal char (no escaping).
                # Range: ch '-' hi, where hi is not the closing ']'.
                if i + 2 < n and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range in class")
                    for code in range(ord(lo), ord(hi) + 1):
                        members.add(chr(code))
                    i += 3
                else:
                    # Literal member (covers ']' as first member and '-' at edges).
                    members.add(ch)
                    i += 1
            tokens.append(('class', frozenset(members), negate))
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
            result = wi == len(word)
        else:
            tok = tokens[ti]
            kind = tok[0]
            if kind == 'star':
                # Zero or more chars: skip star, or consume one char and retry.
                result = rec(ti + 1, wi) or (wi < len(word) and rec(ti, wi + 1))
            elif wi >= len(word):
                result = False
            elif kind == 'lit':
                result = word[wi] == tok[1] and rec(ti + 1, wi + 1)
            elif kind == 'any':
                result = rec(ti + 1, wi + 1)
            else:  # 'class'
                _, members, negate = tok
                inside = word[wi] in members
                result = (inside != negate) and rec(ti + 1, wi + 1)
        memo[key] = result
        return result

    return rec(0, 0)
