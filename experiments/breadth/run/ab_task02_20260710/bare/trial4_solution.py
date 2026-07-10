def wildcard_match(pattern: str, text: str) -> bool:
    validate_pattern(pattern)
    memo = {}

    def match(p_idx, t_idx):
        if (p_idx, t_idx) in memo:
            return memo[(p_idx, t_idx)]

        if p_idx == len(pattern) and t_idx == len(text):
            return True

        if p_idx == len(pattern):
            return False

        if t_idx == len(text):
            while p_idx < len(pattern):
                if pattern[p_idx] != '*':
                    return False
                p_idx += 1
            return True

        result = False

        if pattern[p_idx] == '*':
            result = match(p_idx + 1, t_idx) or match(p_idx, t_idx + 1)
        elif pattern[p_idx] == '?':
            result = match(p_idx + 1, t_idx + 1)
        elif pattern[p_idx] == '\\':
            if pattern[p_idx + 1] == text[t_idx]:
                result = match(p_idx + 2, t_idx + 1)
        elif pattern[p_idx] == '[':
            if char_matches_class(pattern, p_idx, text[t_idx]):
                class_end = find_char_class_end(pattern, p_idx)
                result = match(class_end + 1, t_idx + 1)
        else:
            if pattern[p_idx] == text[t_idx]:
                result = match(p_idx + 1, t_idx + 1)

        memo[(p_idx, t_idx)] = result
        return result

    return match(0, 0)


def validate_pattern(pattern):
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2
        elif pattern[i] == '[':
            class_end = find_char_class_end(pattern, i)
            if class_end >= len(pattern):
                raise ValueError("Unclosed character class")
            check_char_class_ranges(pattern, i)
            i = class_end + 1
        else:
            i += 1


def find_char_class_end(pattern, start):
    i = start + 1

    if i < len(pattern) and pattern[i] == '!':
        i += 1

    if i < len(pattern) and pattern[i] == ']':
        i += 1

    while i < len(pattern):
        if pattern[i] == '\\':
            i += 2
        elif pattern[i] == ']':
            return i
        else:
            i += 1

    return len(pattern)


def check_char_class_ranges(pattern, start):
    i = start + 1

    if i < len(pattern) and pattern[i] == '!':
        i += 1

    if i < len(pattern) and pattern[i] == ']':
        i += 1

    end = find_char_class_end(pattern, start)
    while i < end:
        if pattern[i] == '\\':
            i += 2
        elif i + 2 < end and pattern[i + 1] == '-':
            next_char = pattern[i + 2]
            if next_char != ']':
                if ord(pattern[i]) > ord(next_char):
                    raise ValueError("Reversed range")
                i += 3
            else:
                i += 1
        else:
            i += 1


def char_matches_class(pattern, class_start, char):
    i = class_start + 1

    negate = False
    if i < len(pattern) and pattern[i] == '!':
        negate = True
        i += 1

    if i < len(pattern) and pattern[i] == ']':
        if char == ']':
            return not negate
        i += 1

    end = find_char_class_end(pattern, class_start)
    while i < end:
        if pattern[i] == '\\':
            if i + 1 < end and pattern[i + 1] == char:
                return not negate
            i += 2
        elif i + 2 < end and pattern[i + 1] == '-':
            next_char = pattern[i + 2]
            if next_char != ']':
                if ord(pattern[i]) <= ord(char) <= ord(next_char):
                    return not negate
                i += 3
            else:
                if pattern[i] == char:
                    return not negate
                i += 1
        else:
            if pattern[i] == char:
                return not negate
            i += 1

    return negate
