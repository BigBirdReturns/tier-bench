def wildcard_match(pattern: str, text: str) -> bool:
    # Validate pattern for malformedness upfront
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2  # Skip escape sequence
        elif pattern[i] == '[':
            # Find the closing ]
            j = i + 1
            if j < len(pattern) and pattern[j] == '!':
                j += 1
            if j < len(pattern) and pattern[j] == ']':
                j += 1  # ] as first character is literal
            while j < len(pattern) and pattern[j] != ']':
                j += 1
            if j >= len(pattern):
                raise ValueError("Unclosed character class")
            i = j + 1
        else:
            i += 1

    memo = {}

    def parse_class(start):
        i = start + 1  # Skip [
        negated = False

        if i < len(pattern) and pattern[i] == '!':
            negated = True
            i += 1

        members = []

        if i < len(pattern) and pattern[i] == ']':
            members.append(('char', ']'))
            i += 1

        while i < len(pattern):
            if pattern[i] == ']':
                return negated, members, i + 1

            if i + 2 < len(pattern) and pattern[i + 1] == '-' and pattern[i + 2] != ']':
                low = pattern[i]
                high = pattern[i + 2]
                if ord(low) > ord(high):
                    raise ValueError("Reversed range")
                members.append(('range', (low, high)))
                i += 3
            else:
                members.append(('char', pattern[i]))
                i += 1

        raise ValueError("Unclosed character class")

    def matches_char_in_class(negated, members, char):
        matched = False
        for typ, val in members:
            if typ == 'char':
                if char == val:
                    matched = True
                    break
            elif typ == 'range':
                if val[0] <= char <= val[1]:
                    matched = True
                    break

        return matched if not negated else not matched

    def match_recursive(p_idx, t_idx):
        if (p_idx, t_idx) in memo:
            return memo[(p_idx, t_idx)]

        result = False

        if p_idx == len(pattern):
            result = t_idx == len(text)
        elif pattern[p_idx] == '*':
            if match_recursive(p_idx + 1, t_idx):
                result = True
            elif t_idx < len(text) and match_recursive(p_idx, t_idx + 1):
                result = True
        elif pattern[p_idx] == '?':
            if t_idx < len(text) and match_recursive(p_idx + 1, t_idx + 1):
                result = True
        elif pattern[p_idx] == '[':
            negated, members, end_pos = parse_class(p_idx)
            if t_idx < len(text) and matches_char_in_class(negated, members, text[t_idx]):
                result = match_recursive(end_pos, t_idx + 1)
        elif pattern[p_idx] == '\\':
            if p_idx + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            next_char = pattern[p_idx + 1]
            if t_idx < len(text) and text[t_idx] == next_char:
                result = match_recursive(p_idx + 2, t_idx + 1)
        else:
            if t_idx < len(text) and text[t_idx] == pattern[p_idx]:
                result = match_recursive(p_idx + 1, t_idx + 1)

        memo[(p_idx, t_idx)] = result
        return result

    return match_recursive(0, 0)
