from functools import lru_cache


def wildcard_match(pattern: str, text: str) -> bool:
    def parse() -> list[tuple]:
        tokens = []
        i = 0
        n = len(pattern)
        while i < n:
            c = pattern[i]
            if c == "\\":
                if i + 1 >= n:
                    raise ValueError("trailing backslash")
                tokens.append(("lit", pattern[i + 1]))
                i += 2
            elif c == "*":
                tokens.append(("star",))
                i += 1
            elif c == "?":
                tokens.append(("any",))
                i += 1
            elif c == "[":
                j = i + 1
                negate = False
                if j < n and pattern[j] == "!":
                    negate = True
                    j += 1

                members = []
                first = True
                while True:
                    if j >= n:
                        raise ValueError("unclosed class")
                    ch = pattern[j]
                    if ch == "]" and not first:
                        j += 1
                        break
                    if ch == "]" and first:
                        members.append(("ch", "]"))
                        j += 1
                        first = False
                        continue
                    if j + 2 < n and pattern[j + 1] == "-" and pattern[j + 2] != "]":
                        lo = ch
                        hi = pattern[j + 2]
                        if ord(lo) > ord(hi):
                            raise ValueError("reversed range")
                        members.append(("range", lo, hi))
                        j += 3
                        first = False
                        continue
                    members.append(("ch", ch))
                    j += 1
                    first = False

                tokens.append(("class", negate, tuple(members)))
                i = j
            else:
                tokens.append(("lit", c))
                i += 1
        return tokens

    tokens = parse()

    def class_ok(negate: bool, members: tuple, ch: str) -> bool:
        hit = False
        for kind, *rest in members:
            if kind == "ch":
                if ch == rest[0]:
                    hit = True
                    break
            else:
                lo, hi = rest
                if lo <= ch <= hi:
                    hit = True
                    break
        return hit != negate

    @lru_cache(maxsize=None)
    def match(ti: int, si: int) -> bool:
        if ti == len(tokens):
            return si == len(text)

        tok = tokens[ti]
        kind = tok[0]
        if kind == "star":
            return match(ti + 1, si) or (si < len(text) and match(ti, si + 1))
        if si >= len(text):
            return False
        if kind == "any":
            return match(ti + 1, si + 1)
        if kind == "lit":
            return text[si] == tok[1] and match(ti + 1, si + 1)
        if kind == "class":
            return class_ok(tok[1], tok[2], text[si]) and match(ti + 1, si + 1)
        return False

    return match(0, 0)
