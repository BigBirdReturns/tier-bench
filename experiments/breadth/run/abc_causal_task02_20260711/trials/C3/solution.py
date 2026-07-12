def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)  # ValueError on malformed pattern, before any counting
    return sum(1 for w in words if _match(tokens, w))


def _parse(pattern: str):
    """Tokenize the pattern.

    Tokens:
      ('star',)                    -- '*'
      ('any',)                     -- '?'
      ('lit', ch)                  -- literal character (incl. escaped)
      ('class', frozenset, neg)    -- character class
    """
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '*':
            tokens.append(('star',))
            i += 1
        elif c == '?':
            tokens.append(('any',))
            i += 1
        elif c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '[':
            chars, neg, i = _parse_class(pattern, i + 1)
            tokens.append(('class', frozenset(chars), neg))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _parse_class(pattern: str, i: int):
    """Parse a character class body starting just after '['.

    Inside a class, backslash is a literal character (not an escape prefix).
    Returns (set_of_chars, negated, index_after_closing_bracket).
    """
    n = len(pattern)
    neg = False
    if i < n and pattern[i] == '!':
        neg = True
        i += 1
    chars = set()
    # ']' as the first member is a literal
    if i < n and pattern[i] == ']':
        chars.add(']')
        i += 1
    while True:
        if i >= n:
            raise ValueError("unclosed character class")
        c = pattern[i]
        if c == ']':
            return chars, neg, i + 1
        # Range: c-d, unless '-' is the last char before ']' (then literal)
        if i + 1 < n and pattern[i + 1] == '-' and i + 2 < n and pattern[i + 2] != ']':
            lo, hi = c, pattern[i + 2]
            if ord(lo) > ord(hi):
                raise ValueError("malformed range %r-%r" % (lo, hi))
            chars.update(chr(o) for o in range(ord(lo), ord(hi) + 1))
            i += 3
        else:
            chars.add(c)  # covers literal '-' at edges and literal backslash
            i += 1


def _tok_matches(tok, ch: str) -> bool:
    kind = tok[0]
    if kind == 'any':
        return True
    if kind == 'lit':
        return ch == tok[1]
    if kind == 'class':
        return (ch in tok[1]) != tok[2]
    return False  # 'star' handled by the matcher itself


def _match(tokens, word: str) -> bool:
    """Iterative wildcard match with star backtracking. O(len(tokens)*len(word))."""
    ti = wi = 0
    star_ti = -1
    star_wi = 0
    nt, nw = len(tokens), len(word)
    while wi < nw:
        if ti < nt and tokens[ti][0] == 'star':
            star_ti = ti
            star_wi = wi
            ti += 1
        elif ti < nt and _tok_matches(tokens[ti], word[wi]):
            ti += 1
            wi += 1
        elif star_ti != -1:
            ti = star_ti + 1
            star_wi += 1
            wi = star_wi
        else:
            return False
    while ti < nt and tokens[ti][0] == 'star':
        ti += 1
    return ti == nt
