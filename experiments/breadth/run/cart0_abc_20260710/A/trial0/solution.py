import re


def _compile(pattern: str):
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '*':
            out.append('.*')
            i += 1
        elif c == '?':
            out.append('.')
            i += 1
        elif c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            out.append(re.escape(pattern[i + 1]))
            i += 2
        elif c == '[':
            i += 1
            members = []  # list of ('char', ch) or ('range', lo, hi)
            negate = False
            if i < n and pattern[i] == '!':
                negate = True
                i += 1
            first = True
            closed = False
            while i < n:
                ch = pattern[i]
                if ch == ']' and not first:
                    closed = True
                    i += 1
                    break
                first = False
                # inside class: backslash is a literal member, no escaping
                if (i + 2 < n and pattern[i + 1] == '-'
                        and pattern[i + 2] != ']'):
                    lo, hi = ch, pattern[i + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("malformed range")
                    members.append(('range', lo, hi))
                    i += 3
                else:
                    members.append(('char', ch))
                    i += 1
            if not closed:
                raise ValueError("unclosed character class")
            parts = []
            for m in members:
                if m[0] == 'char':
                    ch = m[1]
                    if ch in r'\]^-[':
                        parts.append('\\' + ch)
                    else:
                        parts.append(re.escape(ch))
                else:
                    _, lo, hi = m
                    parts.append('%s-%s' % (
                        '\\' + lo if lo in r'\]^-[' else re.escape(lo),
                        '\\' + hi if hi in r'\]^-[' else re.escape(hi)))
            body = ''.join(parts)
            out.append('[%s%s]' % ('^' if negate else '', body))
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile(''.join(out), re.DOTALL)


def count_matches(pattern: str, words: list[str]) -> int:
    rx = _compile(pattern)
    return sum(1 for w in words if rx.fullmatch(w) is not None)
