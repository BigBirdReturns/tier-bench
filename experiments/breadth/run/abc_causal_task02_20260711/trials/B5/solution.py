def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)  # raises ValueError on malformed pattern, always
    return sum(1 for w in words if _match(tokens, w))


def _parse(pattern: str):
    """Tokenize pattern into a list of:
       ('star',) | ('any',) | ('lit', ch) | ('class', frozenset, negated:bool)
    Raises ValueError on malformed input."""
    tokens = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            # escape outside classes; trailing backslash is malformed
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
            members = []
            # ']' as the first member (after optional '!') is a literal
            if i < n and pattern[i] == ']':
                members.append(']')
                i += 1
            closed = False
            while i < n:
                ch = pattern[i]
                if ch == ']':
                    closed = True
                    i += 1
                    break
                # NOTE: inside a class, backslash is a LITERAL member,
                # never an escape prefix ([\] is a valid class = {'\\'}).
                members.append(ch)
                i += 1
            if not closed:
                raise ValueError("unclosed character class")
            charset = set()
            j, m = 0, len(members)
            while j < m:
                if (members[j] != '-' and j + 2 <= m - 1 + 1 and j + 1 < m
                        and members[j + 1] == '-' and j + 2 < m):
                    # range X-Y ('-' not at either edge)
                    lo, hi = members[j], members[j + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError(
                            "malformed range %r-%r in class" % (lo, hi))
                    for code in range(ord(lo), ord(hi) + 1):
                        charset.add(chr(code))
                    j += 3
                else:
                    # literal member (includes '-' at edges, backslash, etc.)
                    charset.add(members[j])
                    j += 1
            tokens.append(('class', frozenset(charset), negated))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word: str) -> bool:
    """DP: dp[j] == True iff tokens[i:] matches word[j:]."""
    T, W = len(tokens), len(word)
    dp = [False] * (W + 1)
    dp[W] = True
    for i in range(T - 1, -1, -1):
        tok = tokens[i]
        ndp = [False] * (W + 1)
        if tok[0] == 'star':
            # right-to-left: '*' matches empty (dp[j]) or eats one char (ndp[j+1])
            for j in range(W, -1, -1):
                ndp[j] = dp[j] or (j < W and ndp[j + 1])
        elif tok[0] == 'any':
            for j in range(W):
                ndp[j] = dp[j + 1]
        elif tok[0] == 'lit':
            ch = tok[1]
            for j in range(W):
                ndp[j] = word[j] == ch and dp[j + 1]
        else:  # class
            _, charset, negated = tok
            for j in range(W):
                ndp[j] = ((word[j] in charset) != negated) and dp[j + 1]
        dp = ndp
    return dp[0]
