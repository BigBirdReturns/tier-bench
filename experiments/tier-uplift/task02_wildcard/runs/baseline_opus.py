def wildcard_match(pattern: str, text: str) -> bool:
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == '\\':
            if i + 1 >= n:
                raise ValueError("trailing backslash")
            tokens.append(('lit', pattern[i + 1]))
            i += 2
        elif c == '*':
            tokens.append(('star', None))
            i += 1
        elif c == '?':
            tokens.append(('any', None))
            i += 1
        elif c == '[':
            j = i + 1
            negate = False
            if j < n and pattern[j] == '!':
                negate = True
                j += 1
            members = []
            first = True
            while True:
                if j >= n:
                    raise ValueError("unclosed class")
                ch = pattern[j]
                if ch == ']' and not first:
                    break
                if j + 2 < n and pattern[j + 1] == '-' and pattern[j + 2] != ']':
                    lo = ch
                    hi = pattern[j + 2]
                    if ord(lo) > ord(hi):
                        raise ValueError("reversed range")
                    members.append(('range', lo, hi))
                    j += 3
                else:
                    members.append(('char', ch))
                    j += 1
                first = False
            tokens.append(('class', negate, members))
            i = j + 1
        else:
            tokens.append(('lit', c))
            i += 1

    def match_token(tok, ch):
        kind = tok[0]
        if kind == 'lit':
            return tok[1] == ch
        if kind == 'any':
            return True
        if kind == 'class':
            negate = tok[1]
            members = tok[2]
            matched = False
            for m in members:
                if m[0] == 'char':
                    if ch == m[1]:
                        matched = True
                        break
                else:
                    if m[1] <= ch <= m[2]:
                        matched = True
                        break
            return matched != negate
        return False

    ti = 0
    si = 0
    star_ti = -1
    star_si = 0
    ntok = len(tokens)
    ntext = len(text)
    while si < ntext:
        if ti < ntok and tokens[ti][0] == 'star':
            star_ti = ti
            star_si = si
            ti += 1
        elif ti < ntok and tokens[ti][0] != 'star' and match_token(tokens[ti], text[si]):
            ti += 1
            si += 1
        elif star_ti != -1:
            ti = star_ti + 1
            star_si += 1
            si = star_si
        else:
            return False
    while ti < ntok and tokens[ti][0] == 'star':
        ti += 1
    return ti == ntok
