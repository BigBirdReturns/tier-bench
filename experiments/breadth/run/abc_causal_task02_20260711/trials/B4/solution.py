def _parse_class(pattern: str, i: int):
    """Parse a character class starting at pattern[i] == '['.

    Inside a class, backslash is a LITERAL character, never an escape prefix.
    Returns (members: frozenset, negated: bool, next_index_after_class).
    Raises ValueError on unclosed class or a range with low > high.
    """
    n = len(pattern)
    j = i + 1
    negated = False
    if j < n and pattern[j] == '!':
        negated = True
        j += 1
    members = set()
    first = True
    while True:
        if j >= n:
            raise ValueError("unclosed character class")
        c = pattern[j]
        if c == ']' and not first:
            j += 1
            break
        first = False
        # Range: current char, '-', endpoint that is not the closing ']'
        if j + 2 < n and pattern[j + 1] == '-' and pattern[j + 2] != ']':
            lo, hi = c, pattern[j + 2]
            if ord(lo) > ord(hi):
                raise ValueError("malformed range in character class: low > high")
            members.update(chr(k) for k in range(ord(lo), ord(hi) + 1))
            j += 3
        else:
            # Literal member: includes backslash, ']' as first member,
            # and '-' at the edges of the class.
            members.add(c)
            j += 1
    return frozenset(members), negated, j


def _tokenize(pattern: str):
    """Compile pattern into tokens; raises ValueError on any malformed syntax."""
    tokens = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == '*':
            if not (tokens and tokens[-1][0] == '*'):
                tokens.append(('*',))
            i += 1
        elif c == '?':
            tokens.append(('?',))
            i += 1
        elif c == '[':
            members, negated, i = _parse_class(pattern, i)
            tokens.append(('class', members, negated))
        elif c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _matches(tokens, word: str) -> bool:
    """Iterative bottom-up DP: dp[wi] == tokens[ti:] matches word[wi:]."""
    nw = len(word)
    dp = [False] * (nw + 1)
    dp[nw] = True
    for ti in range(len(tokens) - 1, -1, -1):
        tok = tokens[ti]
        ndp = [False] * (nw + 1)
        if tok[0] == '*':
            acc = False
            for wi in range(nw, -1, -1):
                acc = acc or dp[wi]
                ndp[wi] = acc
        else:
            for wi in range(nw):
                c = word[wi]
                if tok[0] == '?':
                    ok = True
                elif tok[0] == 'lit':
                    ok = (c == tok[1])
                else:  # class
                    ok = (c in tok[1]) != tok[2]
                ndp[wi] = ok and dp[wi + 1]
        dp = ndp
    return dp[0]


def count_matches(pattern: str, words: list[str]) -> int:
    # Validate/compile the pattern first: a malformed pattern always raises
    # ValueError, regardless of the word list.
    tokens = _tokenize(pattern)
    return sum(1 for w in words if _matches(tokens, w))
