def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _compile(pattern)
    return sum(1 for w in words if _match(tokens, w))


def _compile(pattern: str):
    """Tokenize pattern; raise ValueError on any malformed construct."""
    tokens = []  # ('star',) | ('one',) | ('lit', ch) | ('class', negated, frozenset)
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            tokens.append(("star",))
            i += 1
        elif c == "?":
            tokens.append(("one",))
            i += 1
        elif c == "\\":
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(("lit", pattern[i + 1]))
            i += 2
        elif c == "[":
            i += 1
            negated = False
            if i < n and pattern[i] == "!":
                negated = True
                i += 1
            members = set()
            first = True
            closed = False
            while i < n:
                ch = pattern[i]
                if ch == "]" and not first:
                    closed = True
                    i += 1
                    break
                first = False
                # In-class backslash is a literal character, never an escape.
                if (
                    i + 1 < n
                    and pattern[i + 1] == "-"
                    and i + 2 < n
                    and pattern[i + 2] != "]"
                ):
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range %s-%s" % (lo, hi))
                    for o in range(ord(lo), ord(hi) + 1):
                        members.add(chr(o))
                    i += 3
                else:
                    members.add(ch)
                    i += 1
            if not closed:
                raise ValueError("unclosed character class")
            tokens.append(("class", negated, frozenset(members)))
        else:
            tokens.append(("lit", c))
            i += 1
    return tokens


def _matches_char(tok, ch: str) -> bool:
    kind = tok[0]
    if kind == "one":
        return True
    if kind == "lit":
        return ch == tok[1]
    # class
    _, negated, members = tok
    return (ch in members) != negated


def _match(tokens, word: str) -> bool:
    """Standard wildcard DP: dp[j] = tokens[:j] matches the prefix consumed."""
    m = len(tokens)
    prev = [False] * (m + 1)
    prev[0] = True
    for j in range(1, m + 1):
        prev[j] = prev[j - 1] and tokens[j - 1][0] == "star"
    for ch in word:
        cur = [False] * (m + 1)
        for j in range(1, m + 1):
            tok = tokens[j - 1]
            if tok[0] == "star":
                cur[j] = cur[j - 1] or prev[j]
            else:
                cur[j] = prev[j - 1] and _matches_char(tok, ch)
        prev = cur
    return prev[m]
