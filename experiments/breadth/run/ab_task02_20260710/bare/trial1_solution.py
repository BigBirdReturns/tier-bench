def wildcard_match(pattern: str, text: str) -> bool:
    # Validate pattern
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2
        elif pattern[i] == '[':
            j = i + 1
            if j < len(pattern) and pattern[j] == '!':
                j += 1
            if j < len(pattern) and pattern[j] == ']':
                j += 1
            found = False
            while j < len(pattern):
                if pattern[j] == ']':
                    found = True
                    break
                if j + 1 < len(pattern) and pattern[j + 1] == '-':
                    if j + 2 < len(pattern) and pattern[j + 2] != ']':
                        if pattern[j] > pattern[j + 2]:
                            raise ValueError("Reversed range")
                        j += 3
                    else:
                        j += 1
                else:
                    j += 1
            if not found:
                raise ValueError("Unclosed class")
            i = j + 1
        else:
            i += 1

    memo = {}

    def char_in_class(char, start):
        i = start
        negate = pattern[i] == '!'
        if negate:
            i += 1
        matched = False
        if i < len(pattern) and pattern[i] == ']':
            if char == ']':
                matched = True
            i += 1
        while i < len(pattern) and pattern[i] != ']':
            if i + 1 < len(pattern) and pattern[i + 1] == '-' and i + 2 < len(pattern) and pattern[i + 2] != ']':
                if ord(pattern[i]) <= ord(char) <= ord(pattern[i + 2]):
                    matched = True
                i += 3
            else:
                if char == pattern[i]:
                    matched = True
                i += 1
        return matched != negate

    def find_class_end(start):
        i = start
        if i < len(pattern) and pattern[i] == '!':
            i += 1
        if i < len(pattern) and pattern[i] == ']':
            i += 1
        while i < len(pattern) and pattern[i] != ']':
            i += 1
        return i + 1

    def dp(p_idx, t_idx):
        if (p_idx, t_idx) in memo:
            return memo[(p_idx, t_idx)]

        if p_idx == len(pattern):
            result = t_idx == len(text)
        elif pattern[p_idx] == '\\':
            if t_idx < len(text) and text[t_idx] == pattern[p_idx + 1]:
                result = dp(p_idx + 2, t_idx + 1)
            else:
                result = False
        elif pattern[p_idx] == '*':
            result = dp(p_idx + 1, t_idx)
            if not result and t_idx < len(text):
                result = dp(p_idx, t_idx + 1)
        elif pattern[p_idx] == '?':
            if t_idx < len(text):
                result = dp(p_idx + 1, t_idx + 1)
            else:
                result = False
        elif pattern[p_idx] == '[':
            if t_idx < len(text) and char_in_class(text[t_idx], p_idx + 1):
                result = dp(find_class_end(p_idx + 1), t_idx + 1)
            else:
                result = False
        else:
            if t_idx < len(text) and text[t_idx] == pattern[p_idx]:
                result = dp(p_idx + 1, t_idx + 1)
            else:
                result = False

        memo[(p_idx, t_idx)] = result
        return result

    return dp(0, 0)
