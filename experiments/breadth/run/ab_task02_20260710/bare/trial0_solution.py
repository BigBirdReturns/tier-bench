def wildcard_match(pattern: str, text: str) -> bool:
    validate_pattern(pattern)
    memo = {}

    def match(p_idx, t_idx):
        if (p_idx, t_idx) in memo:
            return memo[(p_idx, t_idx)]

        if p_idx == len(pattern):
            result = t_idx == len(text)
        elif pattern[p_idx] == '*':
            result = match(p_idx + 1, t_idx) or (t_idx < len(text) and match(p_idx, t_idx + 1))
        elif t_idx == len(text):
            result = False
        elif pattern[p_idx] == '?':
            result = match(p_idx + 1, t_idx + 1)
        elif pattern[p_idx] == '[':
            cls_end = find_class_end(pattern, p_idx)
            cls_str = pattern[p_idx:cls_end+1]
            if char_matches_class(text[t_idx], cls_str):
                result = match(cls_end + 1, t_idx + 1)
            else:
                result = False
        elif pattern[p_idx] == '\\':
            if pattern[p_idx + 1] == text[t_idx]:
                result = match(p_idx + 2, t_idx + 1)
            else:
                result = False
        else:
            if pattern[p_idx] == text[t_idx]:
                result = match(p_idx + 1, t_idx + 1)
            else:
                result = False

        memo[(p_idx, t_idx)] = result
        return result

    return match(0, 0)

def validate_pattern(pattern: str):
    i = 0
    while i < len(pattern):
        if pattern[i] == '\\':
            if i + 1 >= len(pattern):
                raise ValueError("Trailing backslash")
            i += 2
        elif pattern[i] == '[':
            cls_end = find_class_end(pattern, i)
            validate_char_class(pattern[i:cls_end+1])
            i = cls_end + 1
        else:
            i += 1

def find_class_end(pattern: str, start: int) -> int:
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
    raise ValueError("Unclosed character class")

def validate_char_class(cls_str: str):
    i = 1
    if i < len(cls_str) - 1 and cls_str[i] == '!':
        i += 1
    if i < len(cls_str) - 1 and cls_str[i] == ']':
        i += 1

    while i < len(cls_str) - 1:
        if cls_str[i] == '\\':
            i += 2
        elif i + 2 < len(cls_str) - 1 and cls_str[i + 1] == '-':
            low = cls_str[i]
            high = cls_str[i + 2]
            if low > high:
                raise ValueError("Invalid character range")
            i += 3
        else:
            i += 1

def char_matches_class(char: str, cls_str: str) -> bool:
    negated = False
    i = 1

    if i < len(cls_str) and cls_str[i] == '!':
        negated = True
        i += 1

    matched = False

    if i < len(cls_str) - 1 and cls_str[i] == ']':
        if char == ']':
            matched = True
        i += 1

    while i < len(cls_str) - 1:
        if cls_str[i] == '\\':
            if i + 1 < len(cls_str) - 1 and cls_str[i + 1] == char:
                matched = True
            i += 2
        elif i + 2 < len(cls_str) - 1 and cls_str[i + 1] == '-':
            low = cls_str[i]
            high = cls_str[i + 2]
            if ord(low) <= ord(char) <= ord(high):
                matched = True
            i += 3
        else:
            if cls_str[i] == char:
                matched = True
            i += 1

    return matched if not negated else not matched
