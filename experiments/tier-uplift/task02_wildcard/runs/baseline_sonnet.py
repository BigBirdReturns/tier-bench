def wildcard_match(pattern: str, text: str) -> bool:
    def parse(pattern):
        tokens = []
        i = 0
        n = len(pattern)
        while i < n:
            c = pattern[i]
            if c == '\\':
                if i + 1 >= n:
                    raise ValueError("trailing backslash with nothing to escape")
                tokens.append(('lit', pattern[i + 1]))
                i += 2
            elif c == '*':
                tokens.append(('star',))
                i += 1
            elif c == '?':
                tokens.append(('any',))
                i += 1
            elif c == '[':
                j = i + 1
                negate = False
                if j < n and pattern[j] == '!':
                    negate = True
                    j += 1
                members = set()
                ranges = []
                first = True
                closed = False
                while j < n:
                    ch = pattern[j]
                    if ch == ']' and not first:
                        closed = True
                        break
                    if ch == ']' and first:
                        members.add(']')
                        j += 1
                        first = False
                        continue
                    if j + 2 < n and pattern[j + 1] == '-' and pattern[j + 2] != ']':
                        lo = ch
                        hi = pattern[j + 2]
                        if ord(lo) > ord(hi):
                            raise ValueError(
                                "malformed character range: low > high"
                            )
                        ranges.append((lo, hi))
                        j += 3
                        first = False
                        continue
                    members.add(ch)
                    j += 1
                    first = False
                if not closed:
                    raise ValueError("unclosed character class")
                tokens.append(('class', members, ranges, negate))
                i = j + 1
            else:
                tokens.append(('lit', c))
                i += 1
        return tokens

    def class_match(tok, ch):
        _, members, ranges, negate = tok
        in_set = ch in members or any(lo <= ch <= hi for lo, hi in ranges)
        return in_set != negate

    def token_matches(tok, ch):
        kind = tok[0]
        if kind == 'lit':
            return ch == tok[1]
        if kind == 'any':
            return True
        if kind == 'class':
            return class_match(tok, ch)
        return False

    tokens = parse(pattern)

    n_tok = len(tokens)
    n_text = len(text)
    ti = 0
    si = 0
    star_ti = -1
    star_si = 0
    while si < n_text:
        if ti < n_tok and tokens[ti][0] != 'star' and token_matches(tokens[ti], text[si]):
            ti += 1
            si += 1
        elif ti < n_tok and tokens[ti][0] == 'star':
            star_ti = ti
            star_si = si
            ti += 1
        elif star_ti != -1:
            ti = star_ti + 1
            star_si += 1
            si = star_si
        else:
            return False

    while ti < n_tok and tokens[ti][0] == 'star':
        ti += 1

    return ti == n_tok
