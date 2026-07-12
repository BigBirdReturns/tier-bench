"""Wildcard pattern matcher.

Syntax:
  *      any sequence (including empty)
  ?      exactly one character
  [...]  one char from a class:
           - leading '!' negates
           - ']' literal if it is the first member
           - '-' literal at the edges, otherwise an ASCII range (low > high
             is malformed -> ValueError)
           - backslash inside a class is a literal character, NOT an escape
           - unclosed class is malformed -> ValueError
  \\      (outside classes) escapes the next character, making it literal;
         a trailing backslash is malformed -> ValueError

A malformed pattern always raises ValueError, never returns a count.
"""


def _parse(pattern: str):
    """Compile pattern into a token list, validating as we go.

    Tokens:
      ('star',)
      ('any',)
      ('lit', ch)
      ('class', negated, frozenset_of_chars)
    """
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '*':
            # Collapse consecutive stars (equivalent, keeps matching cheap).
            if not (tokens and tokens[-1][0] == 'star'):
                tokens.append(('star',))
            i += 1
        elif c == '?':
            tokens.append(('any',))
            i += 1
        elif c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash in pattern")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '[':
            i += 1
            negated = False
            if i < n and pattern[i] == '!':
                negated = True
                i += 1
            members = set()
            first = True
            closed = False
            while i < n:
                ch = pattern[i]
                if ch == ']' and not first:
                    closed = True
                    i += 1
                    break
                # ']' as the first member is literal; falls through below.
                # In-class backslash is a literal char, not an escape prefix.
                if (i + 1 < n and pattern[i + 1] == '-'
                        and i + 2 < n and pattern[i + 2] != ']'):
                    low, high = ch, pattern[i + 2]
                    if ord(low) > ord(high):
                        raise ValueError(
                            "malformed range %r-%r in character class"
                            % (low, high))
                    for code in range(ord(low), ord(high) + 1):
                        members.add(chr(code))
                    i += 3
                else:
                    members.add(ch)
                    i += 1
                first = False
            if not closed:
                raise ValueError("unclosed character class in pattern")
            tokens.append(('class', negated, frozenset(members)))
        else:
            tokens.append(('lit', c))
            i += 1
    return tokens


def _match(tokens, word: str) -> bool:
    """NFA-style simulation: track the set of word positions reachable."""
    m = len(word)
    positions = {0}
    for tok in tokens:
        kind = tok[0]
        if kind == 'star':
            start = min(positions)
            positions = set(range(start, m + 1))
        elif kind == 'any':
            positions = {p + 1 for p in positions if p < m}
        elif kind == 'lit':
            ch = tok[1]
            positions = {p + 1 for p in positions if p < m and word[p] == ch}
        else:  # 'class'
            negated, members = tok[1], tok[2]
            positions = {p + 1 for p in positions
                         if p < m and ((word[p] in members) != negated)}
        if not positions:
            return False
    return m in positions


def count_matches(pattern: str, words: list[str]) -> int:
    tokens = _parse(pattern)  # raises ValueError on malformed pattern
    return sum(1 for w in words if _match(tokens, w))
