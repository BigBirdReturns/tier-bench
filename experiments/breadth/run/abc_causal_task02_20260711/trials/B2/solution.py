def _parse_class(pat: str, i: int):
    """Parse a character class starting at pat[i] == '['.

    Returns (token, next_index). Inside a class, backslash is a LITERAL
    character (never an escape prefix). Raises ValueError on unclosed
    class or a range with low > high.
    """
    n = len(pat)
    j = i + 1
    negate = False
    if j < n and pat[j] == '!':
        negate = True
        j += 1
    chars = set()
    ranges = []
    first = True  # ']' as the first member is a literal
    while True:
        if j >= n:
            raise ValueError("unclosed character class")
        c = pat[j]
        if c == ']' and not first:
            j += 1
            break
        first = False
        # Range X-Y: needs a '-' next and a following char that is not ']'
        # ('-' immediately before ']' is a literal, as is '-' as first member,
        # which is covered because c would then be '-' itself below).
        if j + 2 < n and pat[j + 1] == '-' and pat[j + 2] != ']':
            lo, hi = c, pat[j + 2]
            if ord(lo) > ord(hi):
                raise ValueError("malformed range: low > high")
            ranges.append((lo, hi))
            j += 3
        else:
            chars.add(c)  # backslash lands here as a plain literal member
            j += 1
    return ('class', (negate, chars, ranges)), j


def _parse(pat: str):
    """Tokenize the pattern. Raises ValueError on malformed patterns."""
    tokens = []
    i = 0
    n = len(pat)
    while i < n:
        c = pat[i]
        if c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pat[i + 1]))
            i += 2
        elif c == '*':
            tokens.append(('star', None))
            i += 1
        elif c == '?':
            tokens.append(('any', None))
            i += 1
        elif c == '[':
            tok, i = _parse_class(pat, i)
            tokens.append(tok)
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _matches(tokens, word: str) -> bool:
    memo = {}

    def rec(ti: int, wi: int) -> bool:
        key = (ti, wi)
        if key in memo:
            return memo[key]
        if ti == len(tokens):
            res = wi == len(word)
        else:
            kind, val = tokens[ti]
            if kind == 'star':
                res = rec(ti + 1, wi) or (wi < len(word) and rec(ti, wi + 1))
            elif wi >= len(word):
                res = False
            elif kind == 'any':
                res = rec(ti + 1, wi + 1)
            elif kind == 'lit':
                res = word[wi] == val and rec(ti + 1, wi + 1)
            else:  # class
                negate, chars, ranges = val
                ch = word[wi]
                inside = ch in chars or any(lo <= ch <= hi for lo, hi in ranges)
                res = (inside != negate) and rec(ti + 1, wi + 1)
        memo[key] = res
        return res

    return rec(0, 0)


def count_matches(pattern: str, words: list[str]) -> int:
    # Parse first: a malformed pattern must raise ValueError,
    # never return a count.
    tokens = _parse(pattern)
    return sum(1 for w in words if _matches(tokens, w))
