def count_matches(pattern: str, words: list[str]) -> int:
    """Count how many words the wildcard pattern matches entirely.

    Syntax: '*' any sequence (incl. empty); '?' exactly one char;
    '[...]' character class (ranges by ASCII, leading '!' negates,
    ']' literal as first member, '-' literal at the edges); '\\'
    escapes the next char OUTSIDE classes only — inside a class a
    backslash is an ordinary literal member, not an escape prefix.
    Malformed patterns raise ValueError.
    """
    tokens = _parse(pattern)
    return sum(1 for w in words if _match(tokens, w))


def _parse(pattern: str):
    """Tokenize pattern into a list of tokens.

    Tokens: ('lit', ch) | ('one',) | ('any',) | ('class', negated, frozenset)
    Raises ValueError on malformed input.
    """
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash in pattern")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '*':
            tokens.append(('any',))
            i += 1
        elif c == '?':
            tokens.append(('one',))
            i += 1
        elif c == '[':
            negated, members, i = _parse_class(pattern, i + 1)
            tokens.append(('class', negated, frozenset(members)))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _parse_class(pattern: str, i: int):
    """Parse a character class starting just after '['.

    Returns (negated, members, index_after_closing_bracket).
    Inside the class, backslash is a literal member (no escaping).
    """
    n = len(pattern)
    negated = False
    if i < n and pattern[i] == '!':
        negated = True
        i += 1
    members = set()
    first = True
    while True:
        if i >= n:
            raise ValueError("unclosed character class in pattern")
        c = pattern[i]
        if c == ']' and not first:
            return negated, members, i + 1
        # c is a member character (']' is literal only as first member)
        if (i + 1 < n and pattern[i + 1] == '-'
                and i + 2 < n and pattern[i + 2] != ']'):
            # range low-high; '-' before a closing ']' is a literal edge dash
            lo, hi = c, pattern[i + 2]
            if ord(lo) > ord(hi):
                raise ValueError(
                    "malformed range %r-%r in character class" % (lo, hi))
            members.update(chr(k) for k in range(ord(lo), ord(hi) + 1))
            i += 3
        else:
            members.add(c)
            i += 1
        first = False


def _match(tokens, word: str) -> bool:
    """Backtracking matcher with memoization; requires full-word match."""
    n = len(tokens)
    m = len(word)
    memo = {}

    def rec(ti: int, wi: int) -> bool:
        key = (ti, wi)
        if key in memo:
            return memo[key]
        if ti == n:
            result = (wi == m)
        else:
            tok = tokens[ti]
            kind = tok[0]
            if kind == 'any':
                # match empty, or consume one char and stay on '*'
                result = rec(ti + 1, wi) or (wi < m and rec(ti, wi + 1))
            elif wi >= m:
                result = False
            else:
                ch = word[wi]
                if kind == 'one':
                    ok = True
                elif kind == 'lit':
                    ok = (ch == tok[1])
                else:  # 'class'
                    ok = ((ch in tok[2]) != tok[1])
                result = ok and rec(ti + 1, wi + 1)
        memo[key] = result
        return result

    return rec(0, 0)
