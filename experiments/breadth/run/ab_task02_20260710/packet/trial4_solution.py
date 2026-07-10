def wildcard_match(pattern: str, text: str) -> bool:
    _validate_pattern(pattern)
    memo = {}

    def match(p_idx, t_idx):
        if (p_idx, t_idx) in memo:
            return memo[(p_idx, t_idx)]

        if p_idx == len(pattern):
            result = t_idx == len(text)
        elif pattern[p_idx] == '*':
            result = match(p_idx + 1, t_idx)
            if not result and t_idx < len(text):
                result = match(p_idx, t_idx + 1)
        elif pattern[p_idx] == '?':
            result = t_idx < len(text) and match(p_idx + 1, t_idx + 1)
        elif pattern[p_idx] == '[':
            end_idx = _find_class_end(pattern, p_idx)
            class_content = pattern[p_idx + 1:end_idx]
            result = (t_idx < len(text) and
                     _char_in_class(text[t_idx], class_content) and
                     match(end_idx + 1, t_idx + 1))
        elif pattern[p_idx] == '\\' and p_idx + 1 < len(pattern):
            escaped_char = pattern[p_idx + 1]
            result = (t_idx < len(text) and
                     text[t_idx] == escaped_char and
                     match(p_idx + 2, t_idx + 1))
        else:
            result = (t_idx < len(text) and
                     pattern[p_idx] == text[t_idx] and
                     match(p_idx + 1, t_idx + 1))

        memo[(p_idx, t_idx)] = result
        return result

    return match(0, 0)


def _validate_pattern(pattern):
    if pattern and pattern[-1] == '\\':
        raise ValueError("Trailing backslash")

    i = 0
    while i < len(pattern):
        if pattern[i] == '[':
            end = _find_class_end(pattern, i)
            if end is None:
                raise ValueError("Unclosed character class")

            class_content = pattern[i + 1:end]
            j = 0
            if class_content and class_content[0] == '!':
                j = 1

            if j < len(class_content) and class_content[j] == ']':
                j += 1

            while j < len(class_content):
                if j + 2 <= len(class_content) and class_content[j + 1] == '-':
                    if j + 2 == len(class_content):
                        break
                    low = class_content[j]
                    high = class_content[j + 2]
                    if ord(low) > ord(high):
                        raise ValueError("Reversed range")
                    j += 3
                else:
                    j += 1

            i = end + 1
        else:
            i += 1


def _find_class_end(pattern, start):
    assert pattern[start] == '['
    i = start + 1

    if i >= len(pattern):
        return None

    if pattern[i] == '!':
        i += 1

    if i < len(pattern) and pattern[i] == ']':
        i += 1

    while i < len(pattern) and pattern[i] != ']':
        i += 1

    if i >= len(pattern):
        return None

    return i


def _char_in_class(char, class_content):
    negated = False
    i = 0

    if class_content and class_content[0] == '!':
        negated = True
        i = 1

    if i < len(class_content) and class_content[i] == ']':
        if char == ']':
            return not negated
        i += 1

    found = False
    while i < len(class_content):
        if i + 2 <= len(class_content) and class_content[i + 1] == '-':
            if i + 2 == len(class_content):
                if char == class_content[i] or char == '-':
                    found = True
                break
            else:
                low = class_content[i]
                high = class_content[i + 2]
                if low <= char <= high:
                    found = True
                    break
                i += 3
        else:
            if char == class_content[i]:
                found = True
                break
            i += 1

    if negated:
        return not found
    else:
        return found
