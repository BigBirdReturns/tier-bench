def wildcard_match(pattern: str, text: str) -> bool:
    def parse_class(p, i):
        """Parse a character class starting at pattern[i], return (end_pos, chars, negated)"""
        if pattern[i] != '[':
            raise ValueError("Not a class")

        i += 1
        negated = False
        if i < len(p) and p[i] == '!':
            negated = True
            i += 1

        chars = set()
        first = True

        while i < len(p):
            if p[i] == ']' and not first:
                return i + 1, chars, negated

            first = False

            # Check for range
            if i + 2 < len(p) and p[i + 1] == '-' and p[i + 2] != ']':
                low = ord(p[i])
                high = ord(p[i + 2])
                if low > high:
                    raise ValueError("Reversed range")
                for c in range(low, high + 1):
                    chars.add(chr(c))
                i += 3
            else:
                chars.add(p[i])
                i += 1

        raise ValueError("Unclosed class")

    # Validate pattern
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2
        elif pattern[i] == '[':
            i, _, _ = parse_class(pattern, i)
        else:
            i += 1

    def match(pi, ti):
        if pi == len(pattern):
            return ti == len(text)

        if pattern[pi] == '*':
            # Match zero characters
            if match(pi + 1, ti):
                return True
            # Match one or more characters
            if ti < len(text) and match(pi, ti + 1):
                return True
            return False

        if pattern[pi] == '?':
            if ti >= len(text):
                return False
            return match(pi + 1, ti + 1)

        if pattern[pi] == '[':
            end, chars, negated = parse_class(pattern, pi)
            if ti >= len(text):
                return False
            ch = text[ti]
            if negated:
                if ch not in chars:
                    return match(end, ti + 1)
            else:
                if ch in chars:
                    return match(end, ti + 1)
            return False

        if pattern[pi] == '\\':
            if ti >= len(text) or text[ti] != pattern[pi + 1]:
                return False
            return match(pi + 2, ti + 1)

        # Literal
        if ti >= len(text) or text[ti] != pattern[pi]:
            return False
        return match(pi + 1, ti + 1)

    return match(0, 0)
